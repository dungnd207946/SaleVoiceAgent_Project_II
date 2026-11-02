"""Fixture cho test seam agent.

`client_cfg` / `workspace_cfg` sống ở `tests/modules/config/conftest.py` vì module
config là chỗ dựng chúng. Test seam cần ĐÚNG hai fixture đó — dựng bản thứ hai ở đây
là hai định nghĩa "một workspace đã đăng nhập" sẽ lệch nhau, và cổng seam sẽ đo một
workspace không giống workspace mà test module config đo.

`noqa: F401` là cố ý: import ở đây KHÔNG phải để gọi, mà để pytest thấy fixture trong
namespace của conftest này.
"""

from tests.modules.config.conftest import client_cfg, workspace_cfg  # noqa: F401
