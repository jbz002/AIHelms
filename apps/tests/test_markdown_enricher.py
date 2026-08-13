"""markdown_enricher 单元测试。"""

from services.markdown_enricher import enrich_markdown


def test_enrich_heading_numbered_line_becomes_h2():
    text = "1、获取token"
    assert enrich_markdown(text) == "## 1. 获取token"


def test_enrich_flattened_json_becomes_fenced_block():
    text = '{\n\n"result": true,\n\n"token": "abc",\n\n}'
    assert (
        enrich_markdown(text) == '```json\n{\n"result": true,\n"token": "abc",\n}\n```'
    )


def test_enrich_nested_json_balanced_close():
    text = '{\n\n"date": [\n\n{"name": "x"},\n\n{"name": "y"}\n\n]\n\n}'
    assert enrich_markdown(text) == (
        '```json\n{\n"date": [\n{"name": "x"},\n{"name": "y"}\n]\n}\n```'
    )


def test_enrich_skips_content_inside_existing_fence():
    text = '```\n1、not a heading\n{\n"a": 1\n}\n```'
    assert enrich_markdown(text) == text


def test_enrich_unclosed_object_left_untouched():
    text = '{\n"a": 1\n'
    assert enrich_markdown(text) == text


def test_enrich_empty_string_passthrough():
    assert enrich_markdown("") == ""


def test_enrich_mixed_heading_and_json_realistic_doc():
    text = (
        "1、获取token\n\n"
        "http://x/api/auth/getToken\n\n"
        "（POST请求）\n\n"
        "{\n\n"
        '"result": **true** ,\n\n'
        '"message": "成功"\n\n'
        "}\n\n"
        "说明：result 为 true 同步成功\n"
    )
    result = enrich_markdown(text)
    assert "## 1. 获取token" in result
    assert "```json" in result
    assert '"result": **true** ,' in result
    assert "说明：result 为 true 同步成功" in result


def test_enrich_restores_escaped_underscore_in_text():
    text = "http://x/person/query?token=your\\_token"
    assert enrich_markdown(text) == "http://x/person/query?token=your_token"


def test_enrich_restores_escaped_underscore_in_fenced_json():
    text = '{\n\n"cPsn\\_Num": "0001",\n\n"cPsn\\_Name": "金利峰"\n\n}'
    assert enrich_markdown(text) == (
        '```json\n{\n"cPsn_Num": "0001",\n"cPsn_Name": "金利峰"\n}\n```'
    )


def test_enrich_restores_escaped_underscore_realistic_interface_doc():
    text = (
        "3、查询人员档案信息\n\n"
        "http://x/person/query?token=your\\_token\n\n"
        "{\n\n"
        '"cPsn\\_Num": "0001",\n\n'
        '"cPsn\\_Name": "金利峰"\n\n'
        "}\n"
    )
    result = enrich_markdown(text)
    assert "## 3. 查询人员档案信息" in result
    assert "token=your_token" in result
    assert "cPsn_Num" in result
    assert "cPsn_Name" in result
    assert "\\_" not in result
