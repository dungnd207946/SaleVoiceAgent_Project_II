"""`kind` → class nạp model. Thêm một kind = thêm file trong thư mục này + một dòng ở đây."""

from embed.models.bm25 import Bm25
from embed.models.e5 import E5
from embed.models.siglip2 import Siglip2

# Hai kind visual trỏ cùng class → server cache theo class nên chỉ nạp SigLIP2 một lần.
LOADERS = {"dense": E5, "sparse": Bm25, "visual_text": Siglip2, "visual_image": Siglip2}
