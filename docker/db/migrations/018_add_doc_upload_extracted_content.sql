-- doc_upload_records 新增 extracted_content 列，存储提取后的 Markdown 内容
ALTER TABLE aihelms.doc_upload_records ADD COLUMN IF NOT EXISTS extracted_content TEXT DEFAULT '';
