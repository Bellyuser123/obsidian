(function() {
    const configEl = document.getElementById('anti-cheat-config');
    if (!configEl) return;

    const url = configEl.dataset.url;
    const csrf = configEl.dataset.csrf;
    let strikes = parseInt(configEl.dataset.strikes, 10) || 0;
    const isAdmin = configEl.dataset.isAdmin === 'true';

    // Fast-fail if already disqualified on load (banned on 4th strike)
    if (strikes >= 4 && !isAdmin) {
        triggerDisqualification();
        return;
    }

    // 1. Initial page-load grace period (3000ms) - opening question never triggers false strike
    let pageLoadGracePeriod = true;
    setTimeout(() => {
        pageLoadGracePeriod = false;
    }, 3000);

    // 2. Transition grace period: ONLY activated when entering fullscreen
    let transitionGracePeriod = false;
    let transitionTimer = null;
    function activateTransitionGracePeriod(duration) {
        transitionGracePeriod = true;
        if (transitionTimer) clearTimeout(transitionTimer);
        transitionTimer = setTimeout(() => {
            transitionGracePeriod = false;
        }, duration || 2000);
    }

    // 3. Debounce window for rapid successive events (e.g. Alt+Tab firing both fullscreen exit & blur)
    let lastViolationTime = 0;
    const DEBOUNCE_MS = 1000;

    // 1. CSS Injection for user-select freeze
    const style = document.createElement('style');
    style.innerHTML = `
        body, html, main, #editor, .problem-statement, textarea, input {
            user-select: none !important;
            -webkit-user-select: none !important;
            -moz-user-select: none !important;
            -ms-user-select: none !important;
        }
    `;
    document.head.appendChild(style);

    // 2. Global Clipboard & Action Lock
    const lockEvents = ['copy', 'cut', 'paste', 'contextmenu', 'drag', 'drop'];
    lockEvents.forEach(evtName => {
        document.addEventListener(evtName, function(e) {
            e.preventDefault();
            e.stopPropagation();
        }, true);
    });

    // 3. Telemetry violation submission
    function reportViolation(type, details) {
        if (pageLoadGracePeriod) {
            console.log(`[PROCTOR] Discarding infraction of type ${type} during initial page load grace period.`);
            return;
        }

        if (transitionGracePeriod) {
            console.log(`[PROCTOR] Discarding infraction of type ${type} during fullscreen entry transition grace period.`);
            return;
        }

        const now = Date.now();
        if (now - lastViolationTime < DEBOUNCE_MS) {
            console.log(`[PROCTOR] Debounced violation of type ${type} (${now - lastViolationTime}ms < ${DEBOUNCE_MS}ms).`);
            return;
        }
        lastViolationTime = now;

        const formData = new FormData();
        formData.append('violation_type', type);
        formData.append('details', details || '');
        formData.append('csrfmiddlewaretoken', csrf);

        fetch(url, {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': csrf
            }
        })
        .then(res => res.json())
        .then(data => {
            if (data.action === 'BAN') {
                if (isAdmin) {
                    console.log("[PROCTOR] Admin/Staff user bypasses BAN action.");
                } else {
                    triggerDisqualification();
                }
            } else if (data.action === 'WARN') {
                strikes = data.current_strikes;
                showWarningModal(strikes);
            } else if (data.action === 'IGNORE' || data.action === 'NONE') {
                console.log("[PROCTOR] Staff or exempt action ignored.");
            }
        })
        .catch(err => {
            console.error("[PROCTOR] Telemetry submission failed:", err);
        });
    }

    // Disqualification layout trigger
    function triggerDisqualification() {
        if (isAdmin) return;

        const mainEl = document.querySelector('main');
        if (mainEl) {
            mainEl.innerHTML = `
                <div style="max-width: 600px; margin: 100px auto; padding: 45px; background: #110808; border: 2px solid #ff4060; text-align: center; font-family: 'JetBrains Mono', monospace; color: #ffd0d5; box-shadow: 0 0 40px rgba(255, 64, 96, 0.4); clip-path: polygon(0 0, calc(100% - 15px) 0, 100% 15px, 100% 100%, 15px 100%, 0 calc(100% - 15px));">
                    <div style="font-size: 50px; color: #ff4060; margin-bottom: 20px;">⚠</div>
                    <h1 style="font-family: 'Press Start 2P', monospace; font-size: 20px; color: #ff4060; margin-bottom: 20px; letter-spacing: 2px; text-shadow: 0 0 10px rgba(255, 64, 96, 0.5);">DISQUALIFIED</h1>
                    <p style="font-size: 13px; line-height: 1.6; margin-bottom: 30px;">
                        Your participation has been revoked due to proctoring protocol infractions. All code workspaces are now frozen.
                    </p>
                    <a href="/dashboard/" style="font-family: 'Press Start 2P', monospace; font-size: 9px; padding: 12px 24px; background: #ff4060; color: #110808; text-decoration: none; display: inline-block; clip-path: polygon(0 0, calc(100% - 4px) 0, 100% 4px, 100% 100%, 4px 100%, 0 calc(100% - 4px)); font-weight: bold;">
                        &lt; Return to Dashboard
                    </a>
                </div>
            `;
        }
        hideWarningModal();
        hideFullscreenModal();
    }

    // 4. Modal Warning View
    function showWarningModal(currentStrikes) {
        if (isAdmin) return;

        let modal = document.getElementById('proctor-warning-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'proctor-warning-modal';
            modal.style.position = 'fixed';
            modal.style.top = '0';
            modal.style.left = '0';
            modal.style.width = '100vw';
            modal.style.height = '100vh';
            modal.style.background = 'rgba(10, 10, 15, 0.98)';
            modal.style.zIndex = '99990';
            modal.style.cursor = 'none';
            modal.style.display = 'flex';
            modal.style.alignItems = 'center';
            modal.style.justifyContent = 'center';
            modal.style.fontFamily = "'JetBrains Mono', monospace";
            
            modal.innerHTML = `
                <div style="max-width: 500px; padding: 30px; background: #12121f; border: 1px solid #ff4060; text-align: center; color: #fff; box-shadow: 0 0 25px rgba(255,64,96,0.3); clip-path: polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px)); cursor: none !important;">
                    <h2 style="font-family: 'Press Start 2P', monospace; font-size: 14px; color: #ff4060; margin-bottom: 20px; letter-spacing: 2px;">PROCTOR WARNING</h2>
                    <p style="font-size: 13px; line-height: 1.6; margin-bottom: 20px;">
                        Infraction detected: Window switch, focus loss, or fullscreen exit. 
                        Any deviation from the active contest page is logged.
                    </p>
                    <div id="proctor-strikes-label" style="font-family: 'Press Start 2P', monospace; font-size: 11px; padding: 10px; background: rgba(255,64,96,0.1); border: 1px dashed rgba(255,64,96,0.3); margin-bottom: 25px; color: #ff4060;">
                        STRIKES: ${currentStrikes} / 3 ${currentStrikes >= 3 ? '(FINAL WARNING: 4TH INFRACTION BANS)' : ''}
                    </div>
                    <button id="resume-proctor-btn" style="font-family: 'Press Start 2P', monospace; font-size: 9px; padding: 12px 24px; background: #ff4060; color: #110808; border: none; cursor: none !important; clip-path: polygon(0 0, calc(100% - 4px) 0, 100% 4px, 100% 100%, 4px 100%, 0 calc(100% - 4px)); font-weight: bold;">
                        RESUME CONTEST
                    </button>
                </div>
            `;
            document.body.appendChild(modal);

            modal.querySelector('#resume-proctor-btn').addEventListener('click', enterFullscreen);
        } else {
            modal.querySelector('#proctor-strikes-label').textContent = `STRIKES: ${currentStrikes} / 3 ${currentStrikes >= 3 ? '(FINAL WARNING: 4TH INFRACTION BANS)' : ''}`;
            modal.style.display = 'flex';
        }
        
        document.body.classList.add('proctored-active');
        const workspace = document.querySelector('main');
        if (workspace) workspace.style.filter = 'blur(10px) brightness(0.2)';
        
        const cursor = document.getElementById('cursor') || document.getElementById('custom-cursor');
        if (cursor && cursor.parentElement === document.body) {
            document.body.appendChild(cursor);
        }
    }

    function hideWarningModal() {
        const modal = document.getElementById('proctor-warning-modal');
        if (modal) modal.style.display = 'none';
        const workspace = document.querySelector('main');
        if (workspace) workspace.style.filter = '';
    }

    // 5. Fullscreen Demander Overlay
    function showFullscreenModal() {
        if (isAdmin) return;

        let modal = document.getElementById('proctor-fullscreen-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'proctor-fullscreen-modal';
            modal.style.position = 'fixed';
            modal.style.top = '0';
            modal.style.left = '0';
            modal.style.width = '100vw';
            modal.style.height = '100vh';
            modal.style.background = 'rgba(10, 10, 15, 0.98)';
            modal.style.zIndex = '99990';
            modal.style.cursor = 'none';
            modal.style.display = 'flex';
            modal.style.alignItems = 'center';
            modal.style.justifyContent = 'center';
            modal.style.fontFamily = "'JetBrains Mono', monospace";

            modal.innerHTML = `
                <div style="max-width: 500px; padding: 30px; background: #12121f; border: 1px solid var(--cyan); text-align: center; color: #fff; box-shadow: 0 0 25px rgba(0,229,204,0.3); clip-path: polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px)); cursor: none !important;">
                    <h2 style="font-family: 'Press Start 2P', monospace; font-size: 12px; color: var(--cyan); margin-bottom: 20px; letter-spacing: 2px;">FULLSCREEN REQUIRED</h2>
                    <p style="font-size: 13px; line-height: 1.6; margin-bottom: 25px;">
                        You must enter fullscreen mode to access the contest space. Exiting fullscreen mode during the contest constitutes an infraction.
                    </p>
                    <button id="enter-fullscreen-btn" style="font-family: 'Press Start 2P', monospace; font-size: 9px; padding: 12px 24px; background: var(--cyan); color: #110808; border: none; cursor: none !important; clip-path: polygon(0 0, calc(100% - 4px) 0, 100% 4px, 100% 100%, 4px 100%, 0 calc(100% - 4px)); font-weight: bold;">
                        ENTER FULLSCREEN
                    </button>
                </div>
            `;
            document.body.appendChild(modal);

            modal.querySelector('#enter-fullscreen-btn').addEventListener('click', enterFullscreen);
        } else {
            modal.style.display = 'flex';
        }
        
        document.body.classList.add('proctored-active');
        
        const workspace = document.querySelector('main');
        if (workspace) workspace.style.filter = 'blur(10px) brightness(0.2)';

        const cursor = document.getElementById('cursor') || document.getElementById('custom-cursor');
        if (cursor && cursor.parentElement === document.body) {
            document.body.appendChild(cursor);
        }
    }

    function hideFullscreenModal() {
        const modal = document.getElementById('proctor-fullscreen-modal');
        if (modal) modal.style.display = 'none';
        const warning = document.getElementById('proctor-warning-modal');
        if (!warning || warning.style.display === 'none') {
            const workspace = document.querySelector('main');
            if (workspace) workspace.style.filter = '';
        }
    }

    function enterFullscreen() {
        const docEl = document.documentElement;
        if (docEl.requestFullscreen) {
            docEl.requestFullscreen().then(() => {
                hideFullscreenModal();
                hideWarningModal();
            }).catch(err => {
                console.error("Fullscreen lock failure:", err);
            });
        }
    }

    // 6. Fullscreen Change Handler: Transition grace period ONLY on ENTERING fullscreen
    document.addEventListener('fullscreenchange', function() {
        if (document.fullscreenElement) {
            // ENTERING fullscreen: activate transition grace period
            activateTransitionGracePeriod(2000);
            hideFullscreenModal();
        } else {
            // EXITING fullscreen: immediately report violation (no transition grace period!)
            if (!pageLoadGracePeriod) {
                reportViolation('FULLSCREEN', 'Participant exited fullscreen mode.');
                showFullscreenModal();
            }
        }
    });

    // 7. Focus & Visibility Observers
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            reportViolation('TAB_SWITCH', 'Participant switched tabs/minimized window.');
            showWarningModal(strikes + 1);
        }
    });

    window.addEventListener('blur', function() {
        reportViolation('TAB_SWITCH', 'Participant lost focus on the contest window.');
        showWarningModal(strikes + 1);
    });

    // 8. Key interception
    window.addEventListener('keydown', function(e) {
        if (e.keyCode === 123) {
            e.preventDefault();
            reportViolation('DEVTOOLS', 'F12 key pressed.');
            return false;
        }
        if (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 74 || e.keyCode === 67)) {
            e.preventDefault();
            reportViolation('DEVTOOLS', 'Ctrl+Shift+I/J/C keyboard combo pressed.');
            return false;
        }
        if (e.ctrlKey && e.keyCode === 85) {
            e.preventDefault();
            reportViolation('DEVTOOLS', 'Ctrl+U keyboard shortcut pressed.');
            return false;
        }
    }, true);

    // 9. Low-overhead debugger loop
    setInterval(function() {
        if (document.hidden || !document.hasFocus()) return;
        if (pageLoadGracePeriod || transitionGracePeriod) return;

        const start = performance.now();
        debugger;
        const end = performance.now();
        if (end - start > 400) {
            reportViolation('DEVTOOLS', 'DevTools active execution freeze detected.');
        }
    }, 1000);

    // 10. AI Extension Sandbox Monitor (Phase 3 Optimization)
    const domObserver = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.addedNodes && mutation.addedNodes.length > 0) {
                mutation.addedNodes.forEach(function(node) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        // Skip if the node itself or its ancestors belong to the Ace Editor container
                        if (node.id === 'codeEditor' || (node.closest && node.closest('#codeEditor'))) {
                            return;
                        }

                        const tag = node.tagName.toLowerCase();
                        const id = node.id || '';
                        const className = node.className || '';
                        
                        if (id.startsWith('proctor-') || id === 'cursor' || id === 'matrixCanvas') {
                            return;
                        }

                        const isSuspect = 
                            tag.includes('copilot') || 
                            tag.includes('ghosttext') || 
                            tag.includes('sidepanel') ||
                            id.includes('extension') || 
                            className.includes('extension') || 
                            className.includes('ai-') ||
                            node.hasAttribute('data-extension') ||
                            node.hasAttribute('data-copilot');

                        if (isSuspect) {
                            const details = `Tag: ${tag}, ID: ${id}, Class: ${className}, Outer HTML: ${node.outerHTML.substring(0, 150)}`;
                            reportViolation('DOM_INJECTION', details);
                        }
                    }
                });
            }
        });
    });

    domObserver.observe(document.body, { childList: true, subtree: true });

    // 11. Ace Editor paste lockdown polling (Phase 4)
    function lockAcePaste() {
        const editorEl = document.getElementById('codeEditor');
        if (editorEl && editorEl.env && editorEl.env.editor) {
            const editor = editorEl.env.editor;
            
            // Intercept paste event parameter and hard-set e.text = ""
            editor.on('paste', function(e) {
                e.text = "";
            });

            // Add command override mapping for the generic "paste" string keyword
            editor.commands.addCommand({
                name: 'paste',
                exec: function() {
                    return false;
                }
            });
            console.log("[PROCTOR] Ace Editor paste lock applied successfully.");
        } else {
            setTimeout(lockAcePaste, 50);
        }
    }
    lockAcePaste();

    // 12. Fallback area paste prevention (Phase 4)
    const fallbackEditor = document.getElementById('codeEditorFallback');
    if (fallbackEditor) {
        fallbackEditor.addEventListener('paste', function(e) {
            e.preventDefault();
            e.stopPropagation();
        }, true);
    }

    // Initial triggers on load
    if (!document.fullscreenElement && !isAdmin) {
        showFullscreenModal();
    }
})();
