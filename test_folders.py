from pathlib import Path
from utils import sanitize_folder_name_advanced, validate_and_create_path

def test_folder_creation():
    test_names = [
        "Canal Normal",
        "Canal/Com:Caracteres|Especiais",
        "Canal_Com_Nome_Extremamente_Longo_Que_Pode_Causar_Problemas_No_Sistema",
        "CON",  # Nome reservado Windows
        "Canal com 中文字符"
    ]
    for name in test_names:
        sanitized = sanitize_folder_name_advanced(name)
        print(f"Original: {name}")
        print(f"Sanitizado: {sanitized}")
        print(f"Criando pasta...")
        try:
            path = validate_and_create_path(
                Path("test") / sanitized,
                f"teste {name}"
            )
            print(f"✅ Sucesso: {path}")
        except Exception as e:
            print(f"❌ Erro: {e}")
        print("-" * 50)

if __name__ == "__main__":
    test_folder_creation() 