from app.parsing.excel_reader import _pick_article
from app.services.field_map import classify_header, map_row


def test_tosun_headers_map_article_not_description() -> None:
    raw = {
        "product name / наименование товара": "ТКАНИ МЕБЕЛЬНЫЕ, COMPOSITION 100% OLEFIN",
        "articul/артикул": "SINDRI 162",
        "number of rolls/количество рулонов/штук": 1,
        "q-ty meters / кол-во погонных метров": 40.43,
        "price per meter $/ цена за пог. метр, долл. сша": 6.17,
        "total price, $ / цена, долл. сша": 249.45,
        "widht, m / ширина, м": 1.4,
    }
    article, _model = _pick_article(raw)
    assert article == "SINDRI 162"
    mapped = map_row(raw)
    assert mapped["article"] == "SINDRI 162"
    assert mapped["price"] == 6.17
    assert mapped["amount"] == 249.45
    assert mapped["rolls"] == 1.0
    assert mapped["meters"] == 40.43
    assert "OLEFIN" in (mapped.get("description") or "")


def test_classify_articul_column() -> None:
    assert classify_header("Articul/Артикул") == "article"
    assert classify_header("Product name / Наименование товара") == "description"
    assert classify_header("Number of rolls/Количество рулонов/штук") == "rolls"


def test_skip_directors_and_keep_articles() -> None:
    from app.parsing.product_row import is_junk_text, is_product_article

    assert is_product_article("SINDRI 162") is True
    assert is_product_article("ZIMMY 925") is True
    assert is_product_article("Noble 110") is True
    assert is_product_article("Директор по продажам Mehmet") is False
    assert is_product_article("Генеральный директор Величко И.В.") is False
def test_generic_item_qty_price_table() -> None:
    from app.parsing.table_rows import lines_from_matrix

    rows = [
        ["Item", "Qty", "Unit price", "Amount"],
        ["MD 812", "200", "0.0592", "11.84"],
        ["AB-90", "10", "12.5", "125"],
        ["Sales Director John", "", "", ""],
    ]
    lines = lines_from_matrix(rows, sheet_name="inv")
    articles = {line["article"] for line in lines}
    assert "MD 812" in articles
    assert "AB-90" in articles
    assert not any("Director" in a for a in articles)


def test_unlabeled_and_turkish_tables() -> None:
    from app.parsing.table_rows import lines_from_matrix, lines_from_plaintext
    from app.services.field_map import map_row

    bare = lines_from_matrix(
        [["MD 812", 200, 0.0592, 11.84], ["AB-90", 10, 12.5, 125]],
        sheet_name="bare",
    )
    assert {line["article"] for line in bare} == {"MD 812", "AB-90"}
    mapped = map_row(bare[0]["raw"])
    assert mapped["qty"] == 200
    assert mapped["price"] == 0.0592

    turkish = lines_from_matrix(
        [
            ["Stok Kodu", "Miktar", "Birim Fiyat", "Tutar"],
            ["SINDRI 162", "40.43", "6.17", "249.45"],
        ],
        sheet_name="tr",
    )
    assert turkish[0]["article"] == "SINDRI 162"
    assert map_row(turkish[0]["raw"])["price"] == 6.17

    text_lines = lines_from_plaintext("SINDRI 162 1 40.43 6.17 249.45\nSales Director Mehmet\n")
    assert any(line["article"] == "SINDRI 162" for line in text_lines)
    assert not any("Director" in line["article"] for line in text_lines)

    from app.parsing.table_rows import lines_from_qty_price_text

    invoice_text = "ZIMMY 1.740,82 MT. 5,78 USD 287,97 TL\nSINDRI 40,43 MT. 6,17 USD 307,40 TL\n"
    priced = lines_from_qty_price_text(invoice_text)
    assert {line["article"] for line in priced} == {"ZIMMY", "SINDRI"}


def test_numeric_mill_article_is_kept() -> None:
    from app.parsing.table_rows import lines_from_matrix

    rows = [
        ["Articul/Артикул", "Q-ty meters", "Price per meter $"],
        ["7508 11 101 0801 110501", "42", "9.95"],
    ]
    lines = lines_from_matrix(rows, sheet_name="spec")
    assert lines[0]["article"] == "7508 11 101 0801 110501"


def test_desing_name_and_color_become_article() -> None:
    from app.parsing.table_rows import lines_from_matrix

    rows = [
        ["ROLL NR", "COLOR NR", "DESING NAME", "AMOUNT (M)", "WIDTH"],
        ["Sack nr", "RENK NO", "DESEN ADI", "NETT", "EN"],
        ["2026004044", "2", "LORENSA", "50", "140"],
        ["2026004051", "4", "LORENSA", "36.5", "140"],
        ["-", "-", "Total Roll :", "5", "-"],
    ]
    lines = lines_from_matrix(rows, sheet_name="ceki")
    articles = {line["article"] for line in lines}
    assert "LORENSA 02" in articles
    assert "LORENSA 04" in articles
    assert not any("Total" in a for a in articles)



