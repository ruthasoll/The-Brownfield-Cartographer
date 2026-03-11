from src.analyzers.tree_sitter_analyzer import LanguageRouter
import os

def test_language_router():
    router = LanguageRouter()
    
    # Test cases: (file_path, expected_language_name)
    test_files = [
        ("test.py", "python"),
        ("test.yaml", "yaml"),
        ("test.sql", "sql")
    ]
    
    for file_name, lang_name in test_files:
        parser = router.get_parser(file_name)
        if parser:
            print(f"PASS: Correctly found parser for {file_name} ({lang_name})")
        else:
            print(f"FAIL: Could not find parser for {file_name} ({lang_name})")

    # Verify parser works on a small string
    py_parser = router.get_parser("example.py")
    if py_parser:
        tree = py_parser.parse(b"def hello(): pass")
        if tree.root_node.type == "module":
            print("PASS: Successfully parsed simple Python code")
        else:
            print(f"FAIL: Unexpected tree root type: {tree.root_node.type}")

if __name__ == "__main__":
    test_language_router()
