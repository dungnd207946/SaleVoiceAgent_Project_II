# SaleVoiceAgent — Project II

Repo tổng hợp mã nguồn của dự án. Mỗi thư mục là một repo độc lập, được gộp vào đây
bằng `git subtree` (giữ nguyên lịch sử commit):

| Thư mục | Nội dung |
|---|---|
| `agent/` | Voice agent (LLM, STT/TTS pipeline, gateway) |
| `backend/` | Backend portal — domain cửa hàng điện thoại |
| `frontend/` | Giao diện web |
| `models/` | Service model: TTS OmniVoice, STT, lipsync MuseTalk, embed, speaker |
| `tts-data/` | Script sinh dữ liệu TTS (dataset không kèm theo) |

Dataset, checkpoint model và thư viện không được đưa lên repo.

## Cập nhật từ các repo con

```bash
git subtree pull --prefix=agent    ../project_II/agent    dungnd
git subtree pull --prefix=backend  ../project_II/backend  dungnd
git subtree pull --prefix=frontend ../project_II/frontend dungnd
git subtree pull --prefix=models   ../project_II/models   dungnd
```
