"""
home/rule_checker.py
--------------------
Static analysis gate using Tree-sitter.
Runs BEFORE code reaches the Docker container.

Returns a list of rule violation dicts (empty = all rules passed).
Each violation: {'rule_type': str, 'keyword': str, 'message': str}

Supported rule types (matches ProblemRule.RULE_TYPES):
  MANDATORY  — code MUST contain this keyword/construct in an active call/usage context
  FORBIDDEN  — code MUST NOT contain this keyword/construct in an active call/usage context
  STRUCTURAL — structural checks (e.g. 'recursion', 'for', 'while')
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ProblemRule

# ---------------------------------------------------------------------------
# Language slug → (grammar_module_path, grammar_function_name)
# Imported lazily to avoid loading all grammars on startup.
# ---------------------------------------------------------------------------
_GRAMMAR_MAP = {
    'python-312': ('tree_sitter_python', 'language'),
    'python':     ('tree_sitter_python', 'language'),
    'cpp':        ('tree_sitter_cpp',    'language'),
    'c':          ('tree_sitter_c',      'language'),
    'javascript': ('tree_sitter_javascript', 'language'),
    'nodejs':     ('tree_sitter_javascript', 'language'),
    'go':         ('tree_sitter_go',     'language'),
    'rust':       ('tree_sitter_rust',   'language'),
    # Java grammar not available via pip; falls back to regex automatically.
}


def _get_parser(language_slug: str):
    """Return a (Parser, Language) tuple for the given slug, or (None, None)."""
    import importlib
    from tree_sitter import Language, Parser

    entry = _GRAMMAR_MAP.get(language_slug.lower())
    if not entry:
        return None, None

    module_name, fn_name = entry
    try:
        mod = importlib.import_module(module_name)
        ts_lang = Language(getattr(mod, fn_name)())
        parser = Parser(ts_lang)
        return parser, ts_lang
    except Exception as exc:
        print(f"[RuleChecker] Could not load grammar for '{language_slug}': {exc}")
        return None, None


# ---------------------------------------------------------------------------
# Node-type maps for STRUCTURAL checks.
# Keys must be lowercase; values are sets of tree-sitter node.type strings.
# ---------------------------------------------------------------------------
_STRUCTURAL_NODES = {
    # Loops
    'for':       {'for_statement', 'for_in_statement', 'for_clause'},
    'while':     {'while_statement'},
    'loop':      {'for_statement', 'for_in_statement', 'while_statement',
                  'for_clause', 'loop_expression'},
    # Conditionals
    'if':        {'if_statement', 'if_expression'},
    'switch':    {'switch_statement', 'switch_expression'},
    # Functions / recursion
    'function':  {'function_definition', 'function_declaration',
                  'method_declaration', 'arrow_function'},
    'recursion': {'__RECURSION__'},   # special — handled by _is_recursive()
    'class':     {'class_definition', 'class_declaration'},
    # Exception handling
    'try':       {'try_statement', 'try_expression'},
    'except':    {'except_clause', 'catch_clause'},
    # Imports
    'import':    {'import_statement', 'import_from_statement',
                  'import_declaration', 'preproc_include'},
    # Inheritance
    'inheritance': {
        'superclasses',         # Python inheritance wrapper node
        'base_class_clause',    # C++ inheritance specification node
        'superclass',           # Java extension node type
    },
}

# ---------------------------------------------------------------------------
# Leaf node types to prune entirely — their text must NEVER match a rule.
# ---------------------------------------------------------------------------
_SKIP_NODE_TYPES = {
    'comment',                       # Python/JS/Rust:  # ...
    'block_comment',                 # C/C++/Go/Rust:   /* ... */
    'line_comment',                  # C/C++/Rust:      // ...
    'string',                        # Generic string literal wrapper
    'string_content',                # Inner string bytes
    'interpreted_string_literal',    # Go "..." strings
    'raw_string_literal',            # Go/Rust raw strings
    'char_literal',                  # C/C++ 'x'
}

# ---------------------------------------------------------------------------
# Call node types — used to detect an identifier in an actual call context.
# ---------------------------------------------------------------------------
_CALL_NODE_TYPES = {
    'call',                  # Python, JS:  foo()
    'call_expression',       # Go, Rust, JS arrow: foo()
    'invocation_expression', # C#
}


# ---------------------------------------------------------------------------
# Walkers
# ---------------------------------------------------------------------------
def _iter_nodes(root_node):
    """Left-to-right DFS iterator over all nodes."""
    stack = [root_node]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))   # reverse → left-to-right pop


def _collect_node_types(root_node) -> set[str]:
    """DFS the AST and return the set of all node types present."""
    found = set()
    for node in _iter_nodes(root_node):
        found.add(node.type)
    return found


def _collect_all_text(root_node, code_bytes: bytes) -> list[str]:
    """
    Collect the text of every *code* leaf node in left-to-right order,
    skipping comments and string literals entirely.
    """
    texts = []
    stack = [root_node]
    while stack:
        node = stack.pop()
        if node.type in _SKIP_NODE_TYPES:
            continue
        if not node.children:
            texts.append(code_bytes[node.start_byte:node.end_byte].decode('utf-8', errors='replace'))
        stack.extend(reversed(node.children))
    return texts


# ---------------------------------------------------------------------------
# Precise call-site scanner
# ---------------------------------------------------------------------------
def _get_call_function_name(call_node, code_bytes: bytes) -> str | None:
    """
    Given a call/call_expression node, return the exact function-name identifier
    token that is *being invoked*, or None if it cannot be determined.

    We look at:
      - child_by_field_name('function')  — tree-sitter standard field
      - first identifier child            — fallback
    """
    # Prefer the named 'function' field (Python, Go, JS)
    fn_node = call_node.child_by_field_name('function')
    if fn_node is None:
        # Fallback: first identifier-typed child
        for child in call_node.children:
            if child.type == 'identifier':
                fn_node = child
                break

    if fn_node is None:
        return None

    # fn_node might be an attribute (e.g. `nums.count`).
    # The outermost identifier is the method name (right side of the dot).
    if fn_node.type == 'attribute':
        attr = fn_node.child_by_field_name('attribute')
        if attr:
            return code_bytes[attr.start_byte:attr.end_byte].decode('utf-8', errors='replace')

    return code_bytes[fn_node.start_byte:fn_node.end_byte].decode('utf-8', errors='replace')


def _find_call_names(root_node, code_bytes: bytes) -> set[str]:
    """
    Walk the AST and return the set of all function/method names that are
    actually *called* (i.e. appear as the function expression of a call node).
    Excludes anything inside comments or string literals.
    """
    names: set[str] = set()
    for node in _iter_nodes(root_node):
        if node.type in _SKIP_NODE_TYPES:
            continue
        if node.type in _CALL_NODE_TYPES:
            name = _get_call_function_name(node, code_bytes)
            if name:
                names.add(name)
    return names


# ---------------------------------------------------------------------------
# Recursion heuristic
# ---------------------------------------------------------------------------
def _is_recursive(root_node, code_bytes: bytes) -> bool:
    """
    Checks whether any function definition contains a call to itself.
    Uses strict name equality on the call's function-name identifier,
    not a substring search on the full call text.
    """
    def_types = {
        'function_definition', 'function_declaration',
        'method_declaration',  'method_definition',
    }
    name_field_types = {'identifier', 'name'}

    for node in _iter_nodes(root_node):
        if node.type not in def_types:
            continue

        # --- Resolve function's own name ---
        fn_name = None
        name_node = node.child_by_field_name('name')
        if name_node and name_node.type in name_field_types:
            fn_name = code_bytes[name_node.start_byte:name_node.end_byte].decode('utf-8', errors='replace')
        else:
            # Fallback: first identifier child
            for child in node.children:
                if child.type in name_field_types:
                    fn_name = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                    break
        if not fn_name:
            continue

        # --- Find the function body ---
        body = node.child_by_field_name('body')
        if body is None:
            for child in node.children:
                if 'body' in child.type or child.type == 'block':
                    body = child
                    break
        if body is None:
            continue

        # --- Check for a self-call with strict equality ---
        for subnode in _iter_nodes(body):
            if subnode.type in _SKIP_NODE_TYPES:
                continue
            if subnode.type in _CALL_NODE_TYPES:
                called_name = _get_call_function_name(subnode, code_bytes)
                if called_name == fn_name:   # strict ==, not `in`
                    return True

    return False


# ---------------------------------------------------------------------------
# Regex fallback (Java, or any language whose grammar failed to load)
# ---------------------------------------------------------------------------
def _regex_check(code: str, keyword: str) -> bool:
    """
    Word-boundary regex search. Uses word boundaries \b and ignores case
    differences completely. Strips single-line comments first to prevent comment false-positives.
    """
    import re
    # Strip // and # style single-line comments to avoid comment false-positives
    stripped = re.sub(r'(//.*?$|#.*?$)', '', code, flags=re.MULTILINE)
    pattern = rf"\b{re.escape(keyword)}\b"
    return bool(re.search(pattern, stripped, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def check_rules(code: str, language_slug: str, rules) -> list[dict]:
    """
    Evaluate all ProblemRule objects against the submitted code.

    Args:
        code:          The raw source code string.
        language_slug: The Language.slug value (e.g. 'python-312', 'cpp').
        rules:         QuerySet or iterable of ProblemRule objects.

    Returns:
        List of violation dicts. Empty list = clean submission.
    """
    violations = []
    rule_list = list(rules)
    if not rule_list:
        return violations

    # Filter rules: run it if it matches the current language OR if it is a global rule (language is None)
    active_rules = [
        rule for rule in rule_list 
        if rule.language is None or rule.language.slug == language_slug
    ]
    if not active_rules:
        return violations

    # --- Parse ---
    parser, _ = _get_parser(language_slug)
    code_bytes = code.encode('utf-8')
    tree = None
    node_types_found: set[str] = set()
    if parser:
        try:
            tree = parser.parse(code_bytes)
            node_types_found = _collect_node_types(tree.root_node)
            leaf_texts = _collect_all_text(tree.root_node, code_bytes)
        except Exception as exc:
            print(f"[RuleChecker] Parse error: {exc}")

    # --- Evaluate each rule ---
    for rule in active_rules:
        keyword_lower = rule.keyword.strip().lower()
        keyword_raw   = rule.keyword.strip()
        rule_type     = rule.rule_type

        violated = False

        if keyword_lower.startswith('lines_'):
            try:
                target_lines = int(keyword_lower.split('_')[1])
                if tree:
                    start_row = tree.root_node.start_point[0]
                    end_row = tree.root_node.end_point[0]
                    actual_lines = end_row - start_row + 1

                    if actual_lines != target_lines:
                        violated = True
                else:
                    actual_lines = len([line for line in code.splitlines() if line.strip()])
                    if actual_lines != target_lines:
                        violated = True
            except (ValueError, IndexError):
                pass
            
            if violated:
                violations.append({
                    'rule_type': rule_type,
                    'keyword':   keyword_raw,
                    'message':   rule.error_message,
                })
            continue

        if rule_type == 'STRUCTURAL':
            if tree is None:
                # Bypass tree checks entirely and fall back directly to word boundary check
                found = _regex_check(code, keyword_raw)
            else:
                target_nodes = _STRUCTURAL_NODES.get(keyword_lower)
                if target_nodes is None:
                    # Unknown structural keyword → safe regex fallback
                    found = _regex_check(code, keyword_raw)
                elif '__RECURSION__' in target_nodes:
                    found = _is_recursive(tree.root_node, code_bytes)
                else:
                    found = bool(node_types_found & target_nodes)
            # STRUCTURAL is always treated as MANDATORY (structure must be present)
            violated = not found

        elif rule_type == 'MANDATORY':
            if tree:
                found = any(keyword_raw == text for text in leaf_texts)
            else:
                found = _regex_check(code, keyword_raw)
            violated = not found

        elif rule_type == 'FORBIDDEN':
            if tree:
                found = any(keyword_raw == text for text in leaf_texts)
            else:
                found = _regex_check(code, keyword_raw)
            violated = found

        if violated:
            violations.append({
                'rule_type': rule_type,
                'keyword':   keyword_raw,
                'message':   rule.error_message,
            })

    return violations
