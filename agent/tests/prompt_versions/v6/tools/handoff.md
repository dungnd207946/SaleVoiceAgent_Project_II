# tools/handoff.md — switch_agent + update_customer design

**Mục tiêu:** Thiết kế hai tool trọng yếu của hệ multi-agent sao cho:
1. Không leak cụm "chuyển cuộc gọi" ra khách (ẩn với khách).
2. Handoff carry đủ context — agent kế không cần scan lại history.
3. Luôn gọi song song `update_customer` + `switch_agent` khi đã biết dự án (để FAQ inject cho agent kế).
4. Parallel execution an toàn (tool idempotent, handoff_summary truncate nếu dài).

---

## switch_agent — flow

### Ai gọi tool này?
- **Router** gọi khi cần route cuộc gọi đầu sang consultant/support.
- **Consultant** gọi khi khách đã ký hợp đồng (cần support-CRM), hoặc khi khách hoàn thành pre-sale (về router kết cuộc).
- **Support** gọi khi khách quay lại hỏi mua mới (về consultant), hoặc về router để chào kết thúc.

### Ai KHÔNG gọi tool này?
- Agent đang active **không** gọi switch_agent với target = chính mình. Ví dụ Consultant gọi `switch_agent("consultant")` là self-call — no-op, đã được enforce trong `streaming.py:_detect_agent_switch()`.
- **Support escalation** KHÔNG dùng switch_agent. Dùng `escalate(action="transfer")` — đây là chuyển cho chuyên viên người thật, khách cần biết.

### Parameters
```json
{
  "target_agent": "consultant" | "support" | "router",
  "handoff_summary": "<1-2 câu, max 200 chars>",
  "suggested_skill": "info" | "pricing" | "advisor" | "booking" | "crm" | "escalation" | ""
}
```

### handoff_summary — nguyên tắc viết

Phải chứa:
1. **Tên khách** (nếu biết): "Anh Cường", "Chị Hoa", hoặc "Quý Khách".
2. **Dự án** (nếu biết): mã hoặc tên đầy đủ.
3. **Nhu cầu chính**: động từ + đối tượng.
4. **Context quan trọng** nếu có: mục đích (ở/đầu tư), ngân sách, tình trạng (đã mua/chưa).

### Ví dụ handoff_summary

| Tình huống | Tốt | Yếu |
|---|---|---|
| Router → Consultant (pre-sale) | "Anh Cường hỏi căn 3PN dưới 10 tỷ tại NCLB, mua để ở." | "hỏi giá" |
| Router → Support (đã mua) | "Chị Hoa đã mua căn tại NCTH, hỏi tiến độ bàn giao, lo bị trễ." | "hỗ trợ sau mua" |
| Consultant → Support (cần CRM) | "Anh Minh đã ký HĐ tại NCLB, hỏi còn phải đóng bao nhiêu đợt." | "chuyển sang hỗ trợ" |
| Consultant → Router (kết thúc) | "Khách đã đặt lịch xem NCTH 15/5/2026 9h, không còn yêu cầu khác." | "xong rồi" |
| Support → Consultant (hỏi mua thêm) | "Chị Mai đã có căn 2PN tại NPLB, hỏi có dự án nào đầu tư ngoài Long Biên không." | "hỏi thêm" |

### suggested_skill — lý do tồn tại

Router không biết toàn bộ skill của consultant. Field này là **hint** cho registry chọn skill active:
- Nếu router chắc chắn ("khách hỏi giá" → "pricing"), đặt hint.
- Nếu không chắc ("tư vấn chung"), đặt "".

Registry dùng hint + trigger_keywords (từ skill_manifest) + fallback intent classifier (khi cần) để quyết định skill active. Hint chỉ là prior, không phải quyết định cuối.

### Speech pattern khi gọi switch_agent

**Trong cùng response với tool call**, agent PHẢI xuất một câu ack ngắn:

| Target | Câu ack mẫu |
|---|---|
| consultant (pre-sale) | "Dạ để em tìm hiểu thông tin {{project_name}} cho {{addressing}} ạ." |
| consultant (advisor chung) | "Dạ để em tư vấn cho {{addressing}} ngay ạ." |
| support | "Dạ em kiểm tra thông tin cho {{addressing}} ạ." |
| router (kết thúc topic) | "Dạ, {{addressing}} còn cần em hỗ trợ gì nữa không ạ?" |

Nguyên tắc: nói TỰ NHIÊN như đang tự xử lý. Khách không biết bên trong có nhiều AI.

---

## update_customer — flow

### Khi nào gọi
- Khi khách cung cấp: tên, số điện thoại, dự án quan tâm, mục đích mua, ngân sách, khu vực ưu tiên, số phòng ngủ, email.
- Gọi NGAY trong cùng response, không đợi lượt sau.
- Có thể gọi **song song** với tool khác (`update_customer` luôn idempotent, an toàn khi chạy đồng thời với noble_search/get_project_financial/...).

### Quan trọng — khi gọi cùng switch_agent

Router nhận biết dự án khách quan tâm → PHẢI gọi cả hai song song trong CÙNG response:

```
update_customer(project_interest="NCLB")
switch_agent(target_agent="consultant", handoff_summary="...", suggested_skill="pricing")
```

Tại sao?
- `session_store` cần có `customer.project_interest` trước khi agent kế build prompt.
- Registry inject FAQ dựa trên `customer.project_interest`. Thiếu field này → FAQ không được inject → agent kế phải gọi nhiều tool hơn → chậm + tăng hallucination.

Fallback trong registry.py đã có: nếu `project_interest` rỗng nhưng `switch_query` có chứa tên dự án, registry sẽ suy ra. Nhưng parallel call là path chính.

### Parameter rule — "chỉ lưu thông tin khách thực sự nói"

Không suy ra:
- Tên: chỉ update khi khách nói "anh tên X", "tôi là Y" — KHÔNG update khi khách gọi "Chị Luna ơi" (đó là tên agent).
- Gender: suy luận từ xưng hô ("anh" → M, "chị" → F). KHÔNG hỏi trực tiếp.
- Budget: chỉ update khi khách đưa con số cụ thể ("khoảng 5 tỷ", "dưới 10 tỷ").
- Project: update khi khách nêu mã hoặc tên đầy đủ. Không mapping "Palace" → "NPLB" hay "NTTL" (cả hai đều Palace); phải hỏi rõ.

Trường khách không nhắc → để chuỗi rỗng, không guess.

---

## Parallel execution contract

OpenAI-compatible API cho phép multiple `tool_calls` trong cùng assistant message. Khi streaming, agent output:

```
{
  "role": "assistant",
  "content": "Dạ để em tìm hiểu thông tin Noble Crystal Long Biên cho Anh ạ.",
  "tool_calls": [
    {"id": "call_1", "function": {"name": "update_customer", "arguments": "{\"project_interest\": \"NCLB\", ...}"}},
    {"id": "call_2", "function": {"name": "switch_agent", "arguments": "{\"target_agent\": \"consultant\", ...}"}}
  ]
}
```

`streaming.py:StreamingLLM` đã hỗ trợ pattern này. Khi detect có `switch_agent` trong tool_calls:
1. Execute `update_customer` trước (session_store update).
2. Execute `switch_agent`:
   - Save `switch_query`, `active_skill` vào session state.
   - Trigger rebuild prompt cho agent kế.
3. Agent kế đọc state mới, load FAQ, tiếp tục từ turn tiếp theo.

Trường hợp lỗi: nếu `update_customer` fail (Redis down), vẫn cho `switch_agent` chạy (fallback inference trong registry sẽ suy ra project từ switch_query). Không fail toàn bộ tool_calls chỉ vì một tool nhỏ fail.

---

## Cross-agent prompt rebuild

Khi switch_agent xong:

```python
# streaming.py (existing logic)
if switch_detected:
    new_agent = tool_args["target_agent"]
    new_skill = tool_args.get("suggested_skill") or infer_skill(handoff_summary)
    new_prompt = await build_agent_prompt_v4(
        agent_id=new_agent,
        active_skill=new_skill,
        session_id=session_id
    )
    messages[0] = {"role": "system", "content": new_prompt}
    # Inject handoff note vào user-role để trigger next turn
    messages.append({
        "role": "user",
        "content": f"[HANDOFF từ {old_agent}: {handoff_summary}]\n\n{current_user_message}"
    })
    # Continue LLM streaming với prompt mới
```

Expected behavior:
- Layer A+B cached (nếu cùng org, agent persona static) → prefix hit >80%.
- Layer C swap (skill khác) → mới load, nhưng chỉ 500-800 tokens.
- Layer D rebuild (customer_context + FAQ mới + handoff_summary mới) → luôn dynamic.

Cross-agent TTFT kỳ vọng: <500ms overhead vs same-agent (trong khi hiện tại ~2000ms vì phải prefill lại toàn bộ).
