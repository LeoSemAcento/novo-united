import pytest
from pathlib import Path
import shutil
from utils import sanitize_folder_name_advanced, validate_and_create_path, get_media_info

# Testes para sanitize_folder_name_advanced
@pytest.mark.parametrize("input_name,expected", [
    ("Canal Normal", "Canal_Normal"),
    ("Canal/Com:Caracteres|Especiais", "Canal_Com_Caracteres_Especiais"),
    ("Canal_Com_Nome_Extremamente_Longo_Que_Pode_Causar_Problemas_No_Sistema", "Canal_Com_Nome_Extremamente_Longo_Que_Pode_Causar_Pro..."),
    ("CON", "CON_file"),
    ("Canal com 中文字符", "Canal_com_")
])
def test_sanitize_folder_name_advanced(input_name, expected):
    sanitized = sanitize_folder_name_advanced(input_name)
    assert sanitized.startswith(expected[:10])  # Testa início, pois nomes longos são truncados

# Testes para validate_and_create_path
@pytest.mark.parametrize("folder_name", [
    "TestePasta1",
    "Teste/Pasta2",
    "Teste:Pasta3",
    "Teste?Pasta4"
])
def test_validate_and_create_path(folder_name):
    path = Path("test_temp") / sanitize_folder_name_advanced(folder_name)
    result = validate_and_create_path(path, "teste")
    assert result.exists() and result.is_dir()
    # Limpeza
    shutil.rmtree("test_temp", ignore_errors=True)

# Teste para get_media_info (mock simples)
class DummyMessage:
    def __init__(self, id, has_photo=False, has_document=False, mime_type=None, filename=None):
        self.id = id
        self.photo = has_photo
        self.document = None
        if has_document:
            class DummyDoc:
                def __init__(self, mime_type, filename):
                    self.mime_type = mime_type
                    self.attributes = []
                    if filename:
                        class Attr:
                            def __init__(self, file_name):
                                self.file_name = file_name
                        self.attributes.append(Attr(filename))
            self.document = DummyDoc(mime_type, filename)


def test_get_media_info_photo():
    msg = DummyMessage(1, has_photo=True)
    info = get_media_info(msg)
    assert info['type'] == 'imagens'
    assert info['extension'] == '.jpg'


def test_get_media_info_document():
    msg = DummyMessage(2, has_document=True, mime_type='application/pdf', filename='teste.pdf')
    info = get_media_info(msg)
    assert info['type'] == 'documentos' or info['extension'] == '.pdf' 