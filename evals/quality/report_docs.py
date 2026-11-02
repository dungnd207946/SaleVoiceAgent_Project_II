"""Chú giải cho scorecard — metric, trục, loại finding. Một chỗ duy nhất, thuần dữ liệu.

Vì sao cần: report chỉ có tên + số, mà cái quyết định đọc đúng hay sai là **mẫu số**
(`policy_violations` đếm assertion chứ không đếm case; `arg_accuracy` chỉ tính tool
thực sự được gọi; `*_coverage` là "đo được bao nhiêu", không phải "đạt bao nhiêu";
`pass_rate` của trục tool_selection CỐ Ý bi quan). Không ghi ra thì mỗi người đọc
đoán một kiểu, và scorecard rời khỏi máy người chạy là mất ngữ cảnh.

`tests/unit/evals/quality/test_report_docs.py` khoá tính đầy đủ: thêm metric/trục/
loại finding mới mà quên mô tả ở đây là đỏ test, không phải lọt im lặng.
"""

from __future__ import annotations

# metric → mô tả một câu. Nêu rõ MẪU SỐ và hướng đọc khi dễ nhầm.
METRIC_DOCS: dict[str, str] = {
    # ── policy ────────────────────────────────────────────────────────────────
    "policy_violations": (
        "Số ASSERTION `expect` bị trượt (không phải số case) — đếm tuyệt đối, "
        "bộ case càng lớn càng khó giữ 0. Thấp là tốt."
    ),
    "policy_pass_rate": "Tỷ lệ assertion `expect` đạt / tổng assertion. Chỉ để đọc, không gate.",
    # ── tool_selection ────────────────────────────────────────────────────────
    "tool_selection_accuracy": (
        "Tỷ lệ LƯỢT gọi đủ mọi tool khai trong `golden.tools`. Thiếu một tool là trượt cả lượt "
        "dù các tool khác đúng."
    ),
    "arg_accuracy": (
        "Matcher tham số đúng / tổng matcher, mẫu số CHỈ tính tool thực sự được gọi "
        "(tool vắng mặt đã do `tool_selection_accuracy` đếm). Sinh ra để bắt lệch đơn vị giá "
        "VNĐ↔tỷ — loại lỗi không crash mà kết quả vẫn trông hợp lý."
    ),
    "banned_call_rate": (
        "Tỷ lệ lượt có gọi tool nằm trong `golden.banned_tools`, trên các lượt CÓ khai banned. "
        "Thấp là tốt."
    ),
    "irrelevant_call_rate": (
        "Tỷ lệ lượt gọi tool NGOÀI `golden.tools` (miễn trừ `update_customer`). Lưu ý: "
        "`send_media` mà persona cho phép gọi chủ động cũng rơi vào đây — đọc kèm finding."
    ),
    "tool_error_rate": (
        "Tỷ lệ lời gọi tool trả JSON có `error` hoặc `ok: false`, trên TỔNG số lời gọi "
        "(không phải trên số lượt)."
    ),
    # ── trajectory ────────────────────────────────────────────────────────────
    "loop_exhaustion_rate": (
        "Tỷ lệ lượt chạm trần MAX_TOOL_ITERATIONS — agent lặp tool tới hết vòng mà chưa chốt "
        "được câu trả lời. Thấp là tốt."
    ),
    "repeated_call_rate": (
        "Tỷ lệ lượt gọi lặp y hệt `(tên tool, args)` từ 2 lần trở lên — dấu hiệu quay vòng. "
        "Thấp là tốt."
    ),
    "steps_overhead": (
        "Số lời gọi thực tế / số tool trong golden, tính trên lượt có `golden.tools`. "
        "1.0 = không thừa bước; >1 = làm dài dòng."
    ),
    # ── run integrity ─────────────────────────────────────────────────────────
    "cases_errored": (
        "Số case reviewed ném exception khi chạy (agent/infra chết) — hỏng kỹ thuật, "
        "không phải sai nội dung."
    ),
    "cases_missing_trace": "Số case reviewed có trace thiếu lượt so với case — dấu hiệu run dở dang.",
    "cases_gated": (
        "Số case THỰC SỰ được chấm (chỉ `reviewed: true`) — mẫu số ngầm của mọi metric khác. "
        "Nhỏ hơn `cases_scored` nghĩa là còn case chưa duyệt."
    ),
    # ── latency ───────────────────────────────────────────────────────────────
    "ttft_p50_ms": "Trung vị độ trễ tới token ĐẦU TIÊN (ms) — cái khách cảm nhận là 'agent đã phản hồi'.",
    "ttft_p95_ms": "Phân vị 95 độ trễ tới token đầu tiên (ms) — đuôi chậm, sát trải nghiệm xấu nhất.",
    "turn_total_p50_ms": "Trung vị tổng thời gian một lượt (ms), gồm cả thời gian chạy tool.",
    "turn_total_p95_ms": "Phân vị 95 tổng thời gian một lượt (ms).",
    # ── judge: correctness ────────────────────────────────────────────────────
    "answer_correctness_mean": (
        "Điểm 0..1 judge chấm mức khớp NỘI DUNG giữa câu trả lời và `golden.answer`; "
        "khác cách diễn đạt không bị trừ. Cao là tốt."
    ),
    "intent_alignment_rate": (
        "Tỷ lệ lượt judge cho là trả lời đúng TRỌNG TÂM câu khách hỏi, kể cả khi còn thiếu chi tiết."
    ),
    "hallucination_rate": (
        "Tỷ lệ lượt judge gắn cờ có khẳng định mâu thuẫn HOẶC vượt ra ngoài `golden.answer`. "
        "Golden viết quá hẹp sẽ đẩy số này lên dù agent nói đúng — đọc rationale trước khi kết luận."
    ),
    "correctness_coverage": (
        "Phần lượt chấm được / lượt lẽ ra phải chấm. <1 nghĩa là judge lỗi hoặc hết budget — "
        "THIẾU MẪU, không phải điểm kém."
    ),
    # ── judge: groundedness ───────────────────────────────────────────────────
    "grounded_rate": (
        "Tỷ lệ lượt mà MỌI khẳng định trong câu trả lời được dữ liệu tool đỡ. "
        "Thấp = agent nói từ trí nhớ model thay vì từ data tenant."
    ),
    "groundedness_coverage": "Phần lượt groundedness chấm được / lượt có dữ liệu tool để chấm.",
    # ── judge: multiturn ──────────────────────────────────────────────────────
    "context_retention_score": (
        "0..1 — agent có GIỮ và DÙNG thông tin khách đã nói ở lượt trước không; "
        "hỏi lại điều đã biết bị trừ nặng."
    ),
    "consistency_score": "0..1 — các lượt trong cùng hội thoại có tự mâu thuẫn về fact/cam kết không.",
    "multiturn_coverage": "Phần case multi-turn chấm được / tổng case ≥2 lượt.",
    # ── style (linter xác định, mục Style của persona) ────────────────────────
    "style_replies_checked": (
        "Số reply không rỗng của case reviewed được linter văn phong soi — mẫu số của mọi `style_*_rate`."
    ),
    "style_violation_rate": "Tỷ lệ reply vi phạm ÍT NHẤT một luật văn phong (đếm reply, không đếm luật). Thấp là tốt.",
    "style_da_opener_rate": (
        "Tỷ lệ reply mở đầu bằng 'Dạ'. Persona chỉ cho phép khi vừa trả lời câu CÓ/KHÔNG — "
        "regex không phân biệt được nên đếm hết, đọc kèm finding."
    ),
    "style_a_overuse_rate": "Tỷ lệ reply có quá MỘT chữ 'ạ' đứng riêng (persona: tối đa một 'ạ'/tin).",
    "style_markdown_rate": (
        "Tỷ lệ reply chứa ký hiệu markdown (**, #, gạch đầu dòng, bảng, `). Persona cấm tuyệt đối và "
        "`MarkdownStripper` đã lọc stream — >0 là stripper hỏng."
    ),
    "style_multi_question_rate": "Tỷ lệ reply có từ hai dấu hỏi trở lên ('một tin một dấu hỏi').",
    "style_cliche_rate": (
        "Tỷ lệ reply có câu sáo tổng đài ('cảm ơn … đã dành thời gian', 'chúc … ngày tốt lành', "
        "'rất vui được hỗ trợ', 'cần gì cứ nhắn em') khi khách CHƯA chào kết."
    ),
}

# trục → nó chấm cái gì, đọc `checks/failures/pass rate` thế nào.
AXIS_DOCS: dict[str, str] = {
    "policy": (
        "Assertion cứng từ `turns[].expect` (không LLM): chuỗi phải/không được có, regex, "
        "`escalated`, `customer_field`. 1 check = 1 assertion."
    ),
    "tool_selection": (
        "Chấm `golden.tools`/`banned_tools`: gọi đủ tool chưa, tham số đúng chưa, có gọi thừa "
        "hay gọi tool cấm không. `pass rate` ở trục này CỐ Ý bi quan — quan sát không mời "
        "(`tool_error`, `irrelevant_call`) chỉ tăng mẫu số khi chúng xảy ra, nên một lỗi giữa "
        "trăm lời gọi sạch vẫn kéo tỷ lệ xuống rõ. Đọc `metrics`, đừng đọc `pass rate`."
    ),
    "trajectory": (
        "Hình dạng đường đi của agent: lặp vòng tool, gọi trùng, số bước thừa. Không phát biểu "
        "assertion nào nên `checks` luôn 0 — chỉ sinh metric để theo dõi."
    ),
    "run": (
        "Tính toàn vẹn của lượt chạy: case có crash không, trace có thiếu lượt không. "
        "Đây là trục nói 'kết quả có đáng tin để đọc tiếp không'."
    ),
    "latency": "TTFT và tổng thời gian mỗi lượt. Không assertion, `checks` = 0 — chỉ báo cáo.",
    "style": (
        "Linter văn phong xác định (mục Style của persona): 1 check = 1 reply không rỗng, "
        "`failures` = số reply vi phạm ít nhất một luật. Không LLM."
    ),
    "correctness": "LLM judge so câu trả lời với `golden.answer`. `failures` = số lượt bị gắn cờ bịa.",
    "groundedness": (
        "LLM judge kiểm mọi khẳng định trong câu trả lời có được dữ liệu tool đỡ không. "
        "`failures` = số lượt có chi tiết không nguồn."
    ),
    "multiturn": (
        "LLM judge đọc CẢ hội thoại ≥2 lượt: có giữ ngữ cảnh không, có tự mâu thuẫn không. "
        "1 check = 1 case (không phải 1 lượt)."
    ),
}

# kind trong bảng Findings → nghĩa là gì.
FINDING_DOCS: dict[str, str] = {
    # tool_selection
    "tool_selection": "Thiếu tool mà `golden.tools` yêu cầu ở lượt đó.",
    "tool_arg": "Tool CÓ được gọi nhưng tham số không khớp matcher (sai giá trị, sai đơn vị, hoặc thiếu hẳn arg).",
    "irrelevant_call": "Gọi tool ngoài `golden.tools` (`update_customer` được miễn trừ).",
    "banned_call": "Gọi tool nằm trong `golden.banned_tools`.",
    "tool_error": "Tool trả JSON có `error` hoặc `ok: false` — lỗi hạ tầng/dữ liệu, không phải lỗi chọn tool.",
    # trajectory
    "loop_exhausted": "Lượt chạm trần MAX_TOOL_ITERATIONS mà chưa chốt được câu trả lời.",
    "repeated_call": "Gọi lặp y hệt `(tên tool, args)` từ 2 lần trở lên trong cùng một lượt.",
    # run integrity
    "case_error": "Case ném exception khi chạy — agent/infra chết, chưa nói gì về chất lượng nội dung.",
    "missing_trace": "Case có trong bộ case nhưng không có trace — lượt chạy dở dang.",
    "missing_turn": "Trace ít lượt hơn case định nghĩa.",
    # judge
    "hallucination": "Judge thấy khẳng định mâu thuẫn HOẶC vượt ra ngoài `golden.answer`.",
    "ungrounded": "Judge thấy khẳng định không được dữ liệu tool đỡ; `detail` liệt kê chính các khẳng định đó.",
    "multiturn_issue": "Vấn đề mức hội thoại: hỏi lại điều khách đã nói, hoặc tự mâu thuẫn giữa các lượt.",
    "judge_ungraded": "Judge không chấm được lượt này (lỗi/hết budget) — trừ vào `*_coverage`, KHÔNG trừ vào điểm.",
    # style
    "style_da_opener": "Reply mở đầu bằng 'Dạ' (chỉ hợp lệ khi vừa trả lời câu CÓ/KHÔNG).",
    "style_a_overuse": "Quá một chữ 'ạ' đứng riêng trong một reply.",
    "style_markdown": "Reply có ký hiệu markdown — persona cấm, stripper lẽ ra đã lọc.",
    "style_multi_question": "Từ hai dấu hỏi trở lên trong một reply.",
    "style_cliche": "Câu sáo tổng đài khi khách chưa chào kết.",
    # policy (tên = tên key trong `expect`)
    "reply_contains": "Câu trả lời thiếu chuỗi bắt buộc.",
    "reply_contains_any": "Câu trả lời không chứa chuỗi nào trong danh sách bắt buộc-ít-nhất-một.",
    "reply_not_contains": "Câu trả lời chứa chuỗi bị cấm.",
    "reply_matches": "Câu trả lời không khớp regex bắt buộc.",
    "reply_not_matches": "Câu trả lời khớp regex bị cấm (thường là để chặn lộ số/giá).",
    "customer_field": "Hồ sơ khách sau lượt đó không mang giá trị mong đợi — agent chưa ghi nhận thông tin.",
    "escalated": "Chuyển người thật sai kỳ vọng: đáng chuyển mà không chuyển, hoặc không đáng mà vẫn chuyển.",
}

LEGEND = (
    "`missing` = scorer không đo được (mẫu rỗng) — gate đọc nó là FAIL, "
    "vì 'chưa đo' không được phép hiện thành 'đã đạt'."
)

GATES_LEGEND = (
    "Gate loại 1 = ngưỡng tuyệt đối; loại 2 = chặn tụt so với baseline 2026-08-25 — cả hai chốt trong "
    "`evals/quality/data/thresholds.toml`; chỉ những dòng ở đây mới quyết định PASS/FAIL và exit code. "
    "Metric `missing` ⇒ FAIL (fail-closed). Gate `judge = true` chỉ áp khi chạy `--judge`, "
    "không thì hiện `skipped` (cố ý không đo ≠ đo không ra số)."
)

CONFIG_LEGEND = (
    "Điều kiện lượt chạy, để hai run so được với nhau: khác `model`/`agent_temperature`/"
    "`rag_backend` là không so trực tiếp được. `cases_scored` = số case ĐƯỢC CHỌN; "
    "số case thực sự chấm nằm ở metric `cases_gated` (chỉ case `reviewed: true`)."
)

AXES_LEGEND = (
    "`checks` = số phép đo trục đó phát biểu, `failures` = số phép trượt. Trục `checks = 0` "
    "nghĩa là trục đó không assertion gì (chỉ sinh metric), KHÔNG phải 'không có lỗi'."
)

FINDINGS_LEGEND = "`turn` = chỉ số lượt (0-based); `-1` = finding ở mức cả case, không thuộc lượt nào."


def describe(metric: str) -> str:
    """Mô tả của `metric`; chuỗi rỗng nếu chưa khai (render vẫn chạy, không raise)."""
    return METRIC_DOCS.get(metric, "")


def describe_axis(axis: str) -> str:
    return AXIS_DOCS.get(axis, "")


def describe_finding(kind: str) -> str:
    return FINDING_DOCS.get(kind, "")
