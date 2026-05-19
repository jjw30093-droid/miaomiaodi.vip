import os
import re
import json
from pathlib import Path
from minio import Minio
from minio.error import S3Error
from urllib.parse import unquote
import mimetypes

class MinioUploader:
    def __init__(self):
        self.endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
        self.access_key = os.getenv("MINIO_ACCESS_KEY", "minio")
        self.secret_key = os.getenv("MINIO_SECRET_KEY", "minio123")
        self.secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
        self.bucket_name = os.getenv("MINIO_BUCKET_NAME", "football-reports")

        self.client = Minio(
            self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure
        )
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """确保工作 Bucket 存在，并自动配置公开读取权限"""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                print(f"✅ [MinIO] 成功创建 Bucket: {self.bucket_name}")

            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{self.bucket_name}/*"]
                    }
                ]
            }
            self.client.set_bucket_policy(self.bucket_name, json.dumps(policy))
            print(f"✅ [MinIO] 已自动配置 Bucket [{self.bucket_name}] 的公开读取策略")
        except Exception as err:
            print(f"⚠️ [MinIO] 服务器离线或初始化失败 (API 将由于缺乏图片加速能力而降级运行): {err}")

    def upload_image(self, local_path: str, match_id: str, file_name: str) -> str:
        """执行上传任务并返回公开访问 URL"""
        object_name = f"reports/{match_id}/images/{file_name}"
        content_type = mimetypes.guess_type(local_path)[0] or "image/png"
        try:
            self.client.fput_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                file_path=local_path,
                content_type=content_type
            )
            protocol = "https" if self.secure else "http"
            return f"{protocol}://{self.endpoint}/{self.bucket_name}/{object_name}"
        except S3Error as err:
            print(f"❌ [MinIO] 上传失败 {local_path}: {err}")
            return None

def process_markdown_images(markdown_content: str, match_id: str, uploader: MinioUploader) -> str:
    """
    扫描 Markdown 中的本地图片路径，上传 MinIO 并无缝替换。
    """
    # 匹配 ![alt](file:///path)
    pattern = re.compile(r'!\[([^\]]*)\]\((file:///[^)]+)\)')

    def url_replacer(match):
        alt_text = match.group(1)
        local_uri = unquote(match.group(2))
        # 剥离 file:/// 协议标识
        local_path = local_uri[7:] if local_uri.startswith("file:///") else local_uri
        path_obj = Path(local_path)

        if not path_obj.exists() or not path_obj.is_file():
            print(f"⚠️ [Markdown] 本地图片丢失，已执行降级忽略 -> {local_path}")
            return match.group(0)

        file_name = path_obj.name
        minio_url = uploader.upload_image(str(path_obj), match_id, file_name)
        
        if minio_url:
            return f'![{alt_text}]({minio_url})'
        return match.group(0)

    return pattern.sub(url_replacer, markdown_content)
