"""结构化摄取的轻量单元测试，不调用外部模型。"""

import io
import unittest

from app.ingestion.chunking import StructureAwareChunker
from app.ingestion.loaders import load_blocks_from_file
from app.ingestion.structure import StructureAnalyzer


class IngestionTests(unittest.TestCase):
    def split(self, filename: str, content: bytes):
        blocks = load_blocks_from_file(filename, content)
        blocks = StructureAnalyzer().enrich(blocks, filename)
        return blocks, StructureAwareChunker().split(blocks)

    def test_markdown_keeps_section_path(self):
        content = (
            "# 第一章 总则\n\n"
            "第一条 为规范管理，制定本办法。\n\n"
            "第二条 本办法适用于全体学生。\n"
        ).encode("utf-8")

        _, documents = self.split("rules.md", content)

        self.assertGreaterEqual(len(documents), 2)
        self.assertTrue(all(document.metadata.get("section_path") for document in documents))
        self.assertTrue(all(document.metadata.get("parent_key") for document in documents))
        self.assertTrue(all(document.metadata.get("parent_id") for document in documents))
        self.assertTrue(
            all(document.metadata.get("parent_type") == "section" for document in documents)
        )
        self.assertTrue(all(document.metadata.get("logical_hash") for document in documents))

    def test_numbered_items_stay_inside_article(self):
        content = (
            "第七条 基本申请条件：\n\n"
            "1.具有中华人民共和国国籍。\n\n"
            "2.遵守宪法和法律。\n\n"
            "3.必修课成绩排名为专业前10%。\n\n"
            "第八条 本办法由学校负责解释。\n"
        ).encode("utf-8")

        blocks, documents = self.split("rules.txt", content)

        headings = [block for block in blocks if block.block_type == "heading"]
        self.assertEqual(2, len(headings))
        first_article = next(
            document for document in documents
            if "必修课成绩排名为专业前10%" in document.page_content
        )
        self.assertIn("1.具有中华人民共和国国籍", first_article.page_content)

    def test_long_article_heading_is_trimmed_for_section_path(self):
        content = (
            "第二章 学制与学习年限\n\n"
            "第二条 本科标准学制为四年，按四年制定培养方案。在校修读年限一般为四年。\n"
        ).encode("utf-8")

        _, documents = self.split("rules.txt", content)

        document = next(
            item for item in documents
            if "本科标准学制为四年" in item.page_content
        )
        section_path = document.metadata.get("section_path", "")
        self.assertIn("第二条 本科标准学制为四年", section_path)
        self.assertNotIn("在校修读年限", section_path)

    def test_csv_keeps_headers_in_each_record(self):
        content = "姓名,学院\n张三,文学院\n李四,历史学院\n".encode("utf-8")

        blocks, documents = self.split("students.csv", content)

        self.assertEqual(2, len(blocks))
        self.assertTrue(all(block.block_type == "record" for block in blocks))
        self.assertEqual(2, len(documents))
        self.assertIn("姓名: 张三", documents[0].page_content)
        self.assertIn("学院: 文学院", documents[0].page_content)
        self.assertTrue(
            all(document.metadata.get("parent_type") == "record_group" for document in documents)
        )
        self.assertTrue(all(document.metadata.get("parent_id") for document in documents))

    def test_json_array_becomes_records(self):
        content = (
            '[{"title":"奖学金","amount":8000},'
            '{"title":"助学金","amount":3000}]'
        ).encode("utf-8")

        blocks, documents = self.split("awards.json", content)

        self.assertEqual(2, len(blocks))
        self.assertEqual(2, len(documents))
        self.assertIn('"amount": 8000', documents[0].page_content)
        self.assertEqual("record", documents[0].metadata.get("chunk_strategy"))

    def test_txt_without_structure_still_falls_back(self):
        content = ("这是一段没有标题的普通文本。" * 120).encode("utf-8")

        _, documents = self.split("notes.txt", content)

        self.assertGreaterEqual(len(documents), 2)
        self.assertTrue(all(document.metadata.get("chunk_strategy") for document in documents))

    def test_xlsx_table_keeps_header(self):
        import openpyxl

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "奖学金"
        sheet.append(["奖项", "金额"])
        sheet.append(["国家奖学金", 8000])
        buffer = io.BytesIO()
        workbook.save(buffer)

        blocks, documents = self.split("awards.xlsx", buffer.getvalue())

        self.assertEqual(1, len(blocks))
        self.assertEqual("table", blocks[0].block_type)
        self.assertEqual("table", documents[0].metadata.get("chunk_strategy"))
        self.assertIn("| 奖项 | 金额 |", documents[0].page_content)
        self.assertEqual("table", documents[0].metadata.get("parent_type"))


if __name__ == "__main__":
    unittest.main()
