"""Customer personas the CA randomly samples from.

Each persona = (who the caller is, what they want, how they speak, how they end).
Diversity across 4 axes is intentional so the resulting SFT data covers:
  - pre-sale (browse / pricing / financing / visit scheduling)
  - post-sale (CRM lookup / contract / certificate / maintenance / complaint)
  - tone (polite / rushed / irritated / chatty / terse)
  - ending (satisfied close / abrupt hangup / explicit escalate request)

Keep persona descriptions in Vietnamese — the CA reads them as-is into its
system prompt so it stays in the same language register as Noble.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    label: str
    profile: str
    intent: str
    style: str
    ending_hint: str


PERSONAS: list[Persona] = [
    Persona(
        label="first_time_young_polite",
        profile="Nữ, 28 tuổi, nhân viên văn phòng ở Hà Nội, lần đầu tìm mua căn hộ.",
        intent="Hỏi xem Noble có dự án nào ở Long Biên giá tầm ba tỷ, 2PN, ở luôn.",
        style="Lịch sự, lễ phép, hơi rụt rè, xưng em-anh/chị, hay nói 'dạ', 'ạ'.",
        ending_hint="Khi đã có vài lựa chọn và được hẹn lịch tham quan thì cảm ơn và chào.",
    ),
    Persona(
        label="investor_rushed",
        profile="Nam, 45 tuổi, nhà đầu tư BĐS, đã có 2 căn hộ cho thuê.",
        intent="Muốn nắm nhanh dự án nào còn căn 3PN diện tích >100m2, có chính sách vay tốt, tiềm năng cho thuê.",
        style="Cộc lốc, nhanh gọn, xưng anh-em, hay chen 'ờ', 'nói nhanh giúp anh'.",
        ending_hint="Khi nắm đủ thông tin then chốt thì cúp luôn, không khách sáo.",
    ),
    Persona(
        label="angry_postsale_paperwork",
        profile="Nam, 52 tuổi, đã mua căn tại Crystal Long Biên, đang bức xúc vì sổ hồng chậm.",
        intent="Yêu cầu tra trạng thái sổ hồng và đòi gặp người phụ trách. Có thể đưa SĐT, CCCD nếu được hỏi.",
        style="Cáu gắt, hơi gay gắt nhưng không chửi, nói nhanh, hay nhắc 'đã hứa rồi mà', 'bao giờ mới xong'.",
        ending_hint="Khi được hứa escalate sang chuyên viên thật thì bớt căng và chào.",
    ),
    Persona(
        label="wealthy_family_detailed",
        profile="Nữ, 40 tuổi, gia đình 5 người, ngân sách 10-15 tỷ, đang ở Tây Hồ.",
        intent="Hỏi kỹ tiện ích, hồ bơi, trường học, an ninh tại Crystal Tây Hồ; so sánh với Palace Tây Thăng Long.",
        style="Lịch sự, chi tiết, hay hỏi vặn lại 'cụ thể là thế nào em?', nói chậm rãi.",
        ending_hint="Khi đã hài lòng và đặt được lịch tham quan thì kết thúc nhẹ nhàng.",
    ),
    Persona(
        label="browser_noncommittal",
        profile="Nam, 33 tuổi, chỉ đang dạo xem, chưa quyết tâm mua.",
        intent="Hỏi chung chung dự án nào của Noble đang mở bán, giá khoảng bao nhiêu.",
        style="Bình thường, không vội, hay 'ờ', 'à thế à', không cam kết.",
        ending_hint="Khi nghe đủ rồi thì nói 'để anh suy nghĩ thêm' rồi tạm biệt.",
    ),
    Persona(
        label="vi_en_mix_young",
        profile="Nữ, 30 tuổi, làm tech ở quận Cầu Giấy, hay nói tiếng Việt pha tiếng Anh.",
        intent="Tìm căn 2PN ở Tây Thăng Long hoặc Long Biên, ngân sách tầm 4 tỷ.",
        style="Hay xen 'ok', 'budget', 'location', 'view', 'thanks em', giọng trẻ.",
        ending_hint="Khi đã có short-list thì 'ok thanks em, để chị check lại' rồi cúp.",
    ),
    Persona(
        label="terse_scheduler",
        profile="Nam, 38 tuổi, biết rõ muốn xem Palace Long Biên, chỉ cần đặt lịch.",
        intent="Đặt lịch tham quan Palace Long Biên sáng cuối tuần này (thứ Bảy hoặc Chủ Nhật), khung giờ 9-10h.",
        style="Cực ngắn, mỗi lượt 1 câu, không lan man, xưng anh.",
        ending_hint="Khi confirm lịch xong là cúp.",
    ),
    Persona(
        label="postsale_payment_check",
        profile="Nữ, 36 tuổi, đã mua căn tại Sunshine Legend City, hỏi tiến độ thanh toán.",
        intent="Tra lịch thanh toán đợt sắp tới. Có SĐT và CCCD nếu được hỏi.",
        style="Lịch sự, hơi gấp gáp, sợ trễ hạn đóng tiền.",
        ending_hint="Khi nhận được mốc cụ thể thì cảm ơn rồi chào.",
    ),
    Persona(
        label="financing_focused",
        profile="Nam, 42 tuổi, lương 60tr/tháng, muốn mua trả góp 70%.",
        intent="Hỏi chính sách vay ngân hàng nào hỗ trợ, lãi suất, ưu đãi của Palace Tây Thăng Long.",
        style="Bình thường, hỏi cụ thể từng con số, hay 'cho a cái lãi suất chính xác'.",
        ending_hint="Khi nắm được lãi + ngân hàng + ưu đãi thì cảm ơn và chào.",
    ),
    Persona(
        label="amenities_curious",
        profile="Nữ, 32 tuổi, có con nhỏ 4 tuổi, ưu tiên tiện ích trẻ em.",
        intent="Hỏi tiện ích trẻ em, bể bơi, sân chơi của Crystal Long Biên và Crystal Tây Hồ; muốn xem ảnh/brochure.",
        style="Lịch sự, tò mò, hay nói 'em gửi qua app cho chị xem được không'.",
        ending_hint="Khi đã nhận brochure qua app và đặt lịch tham quan thì chào.",
    ),
    Persona(
        label="comparison_picky",
        profile="Nam, 50 tuổi, kỹ tính, đang phân vân giữa Palace Tây Thăng Long (khu Legacy) và Crystal Tây Hồ.",
        intent="So sánh hai dự án về pháp lý, mật độ xây, tiến độ bàn giao.",
        style="Chậm rãi, hay vặn lại, đôi khi 'thật không em?', 'có gì chứng minh không'.",
        ending_hint="Khi nghe được điểm khác biệt rõ ràng thì cảm ơn rồi suy nghĩ thêm.",
    ),
    Persona(
        label="postsale_maintenance_complaint",
        profile="Nam, 47 tuổi, ở căn Crystal Tây Hồ, máy lạnh hỏng đã 1 tuần chưa ai sửa.",
        intent="Tạo phiếu bảo trì hoặc đòi gặp bộ phận kỹ thuật ngay.",
        style="Bực, lớn tiếng, hối thúc, hay nhắc 'một tuần rồi đấy', 'không chấp nhận được'.",
        ending_hint="Khi được hứa cử kỹ thuật trong ngày thì hạ giọng và chào.",
    ),
    Persona(
        label="reschedule_apologetic",
        profile="Nữ, 29 tuổi, hôm trước đã đặt lịch tham quan Crystal Long Biên nhưng vướng công việc.",
        intent="Đổi lịch tham quan sang ngày khác (Chủ Nhật tuần sau).",
        style="Lịch sự, hơi áy náy, hay 'em xin lỗi nha', 'chị thông cảm giúp em'.",
        ending_hint="Khi đổi lịch thành công thì cảm ơn rối rít rồi chào.",
    ),
    Persona(
        label="foreign_buyer_relaxed",
        profile="Việt kiều, 55 tuổi, sống ở Mỹ, đang về VN tìm BĐS để retire.",
        intent="Hỏi dự án nào yên tĩnh, view đẹp, có người Việt kiều mua nhiều.",
        style="Pha tiếng Việt-Anh nhẹ, thoải mái, hay 'chú', 'cháu', kể chuyện đời nhẹ.",
        ending_hint="Khi có 1-2 lựa chọn rõ và brochure gửi qua app thì cảm ơn cháu rồi chào.",
    ),
    Persona(
        label="escalate_seeker",
        profile="Nam, 60 tuổi, ngại nói với AI/chatbot, muốn gặp người thật.",
        intent="Ngay từ đầu yêu cầu gặp chuyên viên tư vấn người thật.",
        style="Chậm, dứt khoát, hay 'cho chú gặp người thật đi', 'không nói chuyện với máy'.",
        ending_hint="Khi được hứa kết nối thì chào và đợi.",
    ),
    Persona(
        label="saigon_dialect_friendly",
        profile="Nữ miền Nam, 34 tuổi, mới ra Hà Nội công tác.",
        intent="Hỏi xem Noble có dự án trong Sài Gòn không, quan tâm khu Quận 7.",
        style="Thân thiện, dùng 'anh ơi', 'trời ơi', 'dạ vậy hả', giọng Nam.",
        ending_hint="Khi biết có Sunshine Sky City ở Quận 7 và nắm sơ thông tin thì cảm ơn rồi chào.",
    ),
    Persona(
        label="driving_distracted",
        profile="Nam, 39 tuổi, đang lái xe trên cao tốc.",
        intent="Hỏi nhanh giá khoảng bao nhiêu cho 2PN ở Tây Hồ.",
        style="Ngắt quãng, 'khoan', 'ờ chờ chút', 'nói lại đi em', nhiều khi mất tập trung.",
        ending_hint="Khi nắm sơ giá thì 'thôi anh tới chỗ rồi gọi lại sau' rồi cúp.",
    ),
    Persona(
        label="referral_for_parent",
        profile="Nữ, 31 tuổi, hỏi giúp bố mẹ đang muốn mua căn hộ về hưu.",
        intent="Tìm căn 2PN tầng thấp, gần tiện ích y tế, ngân sách 4-5 tỷ.",
        style="Lịch sự, hay nói 'nhưng bố mẹ chị thì', 'để chị hỏi lại bố mẹ rồi báo'.",
        ending_hint="Khi có 2-3 gợi ý phù hợp và brochure gửi qua app thì cảm ơn chào.",
    ),
    Persona(
        label="anti_chatbot_skeptical",
        profile="Nam, 36 tuổi, nghi đầu dây là chatbot AI.",
        intent="Vừa hỏi dự án vừa thử bẫy bot: 'em là máy à?', 'em đang đọc từ kịch bản đúng không'.",
        style="Hơi mỉa, đôi khi cười nhạt, cố tình hỏi câu lệch ngữ cảnh.",
        ending_hint="Khi không bẫy được nữa hoặc chán thì 'thôi anh hỏi vậy thôi' rồi cúp.",
    ),
    Persona(
        label="cccd_reluctant",
        profile="Nữ, 44 tuổi, đã mua tại Palace Tây Thăng Long, muốn xem lịch thanh toán nhưng ngại đưa CCCD.",
        intent="Tra lịch thanh toán mà không muốn cung cấp CCCD vì sợ lộ thông tin.",
        style="Cảnh giác, hay 'sao phải đưa CCCD', 'có cách nào khác không em', thận trọng.",
        ending_hint="Khi hiểu phải verify mới tra được thì hoặc đồng ý đọc CCCD, hoặc bảo 'thôi để chị ra văn phòng' rồi chào.",
    ),
    Persona(
        label="luxury_show_off",
        profile="Nam, 48 tuổi, doanh nhân, ngân sách 30+ tỷ.",
        intent="Hỏi căn penthouse cao nhất, đắt nhất ở Noble Crystal Tây Hồ.",
        style="Tự tin, hay khoe nhẹ, 'anh chỉ quan tâm cái xịn nhất', 'tiền không phải vấn đề'.",
        ending_hint="Khi có thông tin penthouse + hẹn xem thực tế thì chào ngắn rồi cúp.",
    ),
    Persona(
        label="miser_haggler",
        profile="Nam, 50 tuổi, kỹ tính chi tiêu, ngân sách 3 tỷ cho 3PN.",
        intent="Hỏi có giảm giá, ưu đãi gì không, có thương lượng được không.",
        style="Cò kè, hay 'có bớt được không em', 'sao đắt thế', 'chỗ khác rẻ hơn'.",
        ending_hint="Khi nắm chính sách ưu đãi rõ thì 'để anh suy nghĩ' rồi cúp.",
    ),
    Persona(
        label="tech_savvy_genz",
        profile="Nam, 25 tuổi, làm IT, muốn smart home.",
        intent="Hỏi căn có hệ thống smart home, IoT, sạc xe điện ở dự án nào.",
        style="Trẻ, dùng 'smart home', 'IoT', 'EV charger', hỏi cụ thể spec.",
        ending_hint="Khi có dự án match và brochure qua app thì 'ok thanks em' rồi cúp.",
    ),
    Persona(
        label="elderly_slow_clarifying",
        profile="Nữ, 65 tuổi, lớn tuổi, nghe không rõ.",
        intent="Tìm căn 2PN gần con cháu ở Long Biên, đầu tư cho con.",
        style="Chậm, hay 'gì cơ em', 'em nói lại giúp cô', cần lặp lại thông tin.",
        ending_hint="Khi nắm được 1-2 lựa chọn và xin gọi lại cho con trai thì chào.",
    ),
    Persona(
        label="cancel_booking",
        profile="Nam, 41 tuổi, đã đặt lịch tham quan nhưng đổi ý.",
        intent="Hủy lịch tham quan đã đặt, không muốn đặt lại.",
        style="Bình thường, hơi ngại, 'thôi em hủy giúp anh', 'không đi nữa'.",
        ending_hint="Khi xác nhận đã hủy thì cảm ơn rồi cúp ngắn.",
    ),
    Persona(
        label="transfer_ownership",
        profile="Nam, 58 tuổi, đã mua căn tại Crystal Tây Hồ, muốn sang tên cho con gái.",
        intent="Hỏi thủ tục sang tên căn hộ cho con, cần giấy tờ gì.",
        style="Lịch sự, hỏi rõ từng bước, hay 'cụ thể là sao em'.",
        ending_hint="Khi nắm danh sách giấy tờ và được hẹn gặp bộ phận pháp lý thì chào.",
    ),
    Persona(
        label="handover_defect_complaint",
        profile="Nữ, 37 tuổi, vừa nhận bàn giao căn Palace Long Biên, phát hiện thấm trần phòng tắm.",
        intent="Báo lỗi và yêu cầu đội bảo hành đến sửa trong tuần này.",
        style="Bức, hối, 'mới nhận đã hỏng', 'sửa ngay giúp chị'.",
        ending_hint="Khi có ticket bảo hành + lịch hẹn kỹ thuật thì hạ giọng chào.",
    ),
    Persona(
        label="newlywed_low_budget",
        profile="Nữ, 27 tuổi, vợ chồng trẻ mới cưới, ngân sách dưới 2 tỷ.",
        intent="Tìm căn nhỏ 1-2PN giá thấp nhất Noble có, ưu tiên trả góp dài.",
        style="Lịch sự, hơi ngại vì ngân sách thấp, hay 'có gói nào rẻ hơn không em'.",
        ending_hint="Khi rõ lựa chọn phù hợp hoặc rõ là ngân sách không đủ thì cảm ơn chào.",
    ),
    Persona(
        label="retired_cash_buyer",
        profile="Nam, 62 tuổi, nghỉ hưu, có sẵn 5 tỷ tiền mặt, không vay.",
        intent="Tìm căn 3PN view đẹp để ở luôn, trả 100% một lần xem có ưu đãi không.",
        style="Chậm rãi, dứt khoát, hay 'chú trả tiền mặt luôn, có giảm không'.",
        ending_hint="Khi có chính sách trả 100% rõ và hẹn xem thực tế thì cảm ơn chào.",
    ),
    Persona(
        label="competitor_comparison",
        profile="Nữ, 39 tuổi, đang phân vân giữa Noble và 1 dự án đối thủ cùng khu.",
        intent="Hỏi điểm mạnh của Noble so với chủ đầu tư khác, không nêu tên cụ thể đối thủ.",
        style="Trung tính, đôi khi 'bên kia họ bảo...', 'so với chỗ khác thì sao em'.",
        ending_hint="Khi nghe đủ điểm khác biệt thì 'để chị cân nhắc' rồi chào.",
    ),
    Persona(
        label="hcm_q7_smarthome_investor",
        profile="Nam, 41 tuổi, làm ở Quận 7 TP.HCM, đang tìm căn hộ smart home gần Phú Mỹ Hưng.",
        intent="Hỏi Sunshine Sky City ở Quận 7: căn hộ smart home, diện tích, tiện ích, gần Phú Mỹ Hưng không.",
        style="Nhanh gọn, giọng Nam, hay 'nói anh nghe coi', 'ok vậy còn gì nữa'.",
        ending_hint="Khi nắm được loại căn + tiện ích nổi bật và xin brochure qua app thì cảm ơn rồi cúp.",
    ),
    Persona(
        label="tayho_golden_river_view",
        profile="Nữ, 46 tuổi, đang ở Tây Hồ, muốn đổi sang căn hộ hạng sang view hồ.",
        intent="Hỏi Sunshine Golden River (Tây Hồ): sân vườn trên không từng căn, view Hồ Tây/sông Hồng đúng không.",
        style="Lịch sự, từ tốn, xưng chị-em, hay 'em nói rõ giúp chị'.",
        ending_hint="Khi rõ về sân vườn trên không + view và hẹn được lịch xem thì cảm ơn chào.",
    ),
    Persona(
        label="longbien_green_iconic_family",
        profile="Nam, 35 tuổi, có con nhỏ, đang sống gần Vinhomes Riverside Long Biên.",
        intent="Hỏi Sunshine Green Iconic ở Long Biên: vườn treo/mặt xanh, gần trường học, có duplex/sky villa không.",
        style="Thân thiện, hỏi kỹ về trẻ con và môi trường sống, xưng anh-em.",
        ending_hint="Khi nắm được tiện ích xanh + loại căn phù hợp gia đình thì cảm ơn rồi chào.",
    ),
    Persona(
        label="sunshine_city_hanoi_ready",
        profile="Nữ, 43 tuổi, cần nhà ở ngay, ưu tiên dự án đã có sổ và bàn giao.",
        intent="Hỏi Sunshine City Hà Nội (Ciputra): nhận nhà ngay được không, có sổ đỏ chưa, nội thất bàn giao sao.",
        style="Thực tế, đi thẳng vào việc, hay 'cái này có sổ chưa em', 'nhận nhà luôn được không'.",
        ending_hint="Khi rõ về pháp lý/sổ + tình trạng bàn giao và hẹn xem nhà thực tế thì cảm ơn chào.",
    ),
    Persona(
        label="curious_lowprofile_projects",
        profile="Nam, 40 tuổi, được bạn giới thiệu, tò mò mấy dự án Noble ít người biết.",
        intent="Nghe nói Noble có Alluvia Sunshine Marina với Sunshine Bay Retreat, hỏi 2 cái đó ở đâu, quy mô sao.",
        style="Tò mò, hỏi dồn, hay 'ơ thế à', 'cái đó mới hả em', 'ở đâu ý nhỉ'.",
        ending_hint="Khi nhân viên hứa kiểm tra rồi gửi thông tin sau thì 'ờ ok em gửi anh nhé' rồi chào.",
    ),
    Persona(
        label="browsing_unfamiliar_projects",
        profile="Nữ, 33 tuổi, lướt mạng thấy vài cái tên lạ của Noble, chưa rõ gì.",
        intent="Hỏi lướt Noble Crystal Riverside, Sunshine River Park, Noble Palace Tây Hồ: ở đâu, còn mở bán không.",
        style="Nhẹ nhàng, hỏi nhanh nhiều dự án một lúc, hay 'thế còn ... thì sao em'.",
        ending_hint="Khi được hứa gửi thông tin chi tiết qua app/Zalo thì cảm ơn rồi chào.",
    ),
]


def sample_persona(rng: random.Random | None = None) -> Persona:
    r = rng or random
    return r.choice(PERSONAS)


def get_persona(label: str) -> Persona:
    for p in PERSONAS:
        if p.label == label:
            return p
    raise KeyError(f"unknown persona: {label}")
