import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'obsidian_proj.settings')
django.setup()

from home.utils import run_in_docker
from home.models import Language

# Test Java
lang_java = Language.objects.get(name='Java 17')
code_java = """
public class Main {
    public static void main(String[] args) {
        System.out.println("hello java");
    }
}
"""
print("Java:", run_in_docker(code_java, lang_java, ""))

# Test Ruby
lang_ruby = Language.objects.get(name='Ruby')
code_ruby = "puts 'hello ruby'"
print("Ruby:", run_in_docker(code_ruby, lang_ruby, ""))

# Test Go
lang_go = Language.objects.get(name='Go (Golang)')
code_go = """
package main
import "fmt"
func main() {
    fmt.Println("hello go")
}
"""
print("Go:", run_in_docker(code_go, lang_go, ""))
