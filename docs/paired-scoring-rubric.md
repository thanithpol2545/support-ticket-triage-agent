# เกณฑ์ตรวจ Audit สำหรับ P04–P07

เกณฑ์ `paired-p04-p07-v1` ใช้กับผล `--audit` ของ Ticket IDs P04A ถึง P07B จาก [paired fixtures](../evaluation/paired_cases.json) ให้ทั้งสองคนตรวจ audit batch เดียวกันจาก SHA และการรันเดียวกัน โดยใช้ผลหลัง Policy ใน `result` สำหรับให้คะแนน และใช้ `proposal` อธิบายว่าโมเดลเสนออะไรและ Policy เปลี่ยนตรงไหน

## วิธีให้คะแนน

1. จับคู่ด้วย `result.ticket_id` แล้วใช้ข้อความต้นฉบับทั้ง thread เป็นหลักฐาน ตรวจเฉพาะ field ที่ระบุในแต่ละแถว
2. แต่ละรายการในคอลัมน์เกณฑ์ผ่านนับหนึ่งข้อ ชุด `urgency / action / assigned_team` นับหนึ่งข้อและต้องผ่านทั้งสามค่า ข้อความรับสำนวนภาษาไทยหรืออังกฤษที่มีความหมายครบ ช่องที่ไม่กล่าวถึงข้อมูลบังคับหรือกล่าวขัดกับ fixture ให้ **FAIL**
3. บันทึก `PASS` หรือ `FAIL` รายข้อพร้อม field และข้อความประกอบ ถ้าไม่มี audit row หรือผลของ field ใช้ไม่ได้ ให้บันทึก `missing` แยกต่างหาก รวมทั้งชุดมี 18 ข้อที่ใช้ประเมินได้ รายงาน `PASS / (PASS + FAIL)` และจำนวนที่ตรวจได้ `(PASS + FAIL) / 18` ควบคู่กัน
4. ช่อง `pending` รอเกณฑ์จาก Support จึงเว้นการตัดสินและตัดออกจากตัวส่วนทั้งสอง ผู้ตรวจไม่เพิ่มกติกาหลังเห็นผลของโมเดล

| เคส | Field และเกณฑ์ผ่าน | ตัวอย่างที่ตก | Pending |
| --- | --- | --- | --- |
| **P04A** ถามว่าทีมอื่นเจอหรือไม่ | (1) `result.summary` ระบุว่ามีรายงาน HTTP 500 จากผู้แจ้งหนึ่งคน และยังไม่ทราบว่าทีมอื่นได้รับผลกระทบหรือไม่ (2) `result.urgency / action / assigned_team` เป็น `medium / route_to_specialist / Technical Support` | Summary ระบุว่าทีมอื่นเจอแล้ว หรือจัดเป็น outage หลายผู้ใช้เพียงเพราะมีคำถาม | — |
| **P04B** ทีมอื่นยืนยันอาการเดียวกัน | (1) `result.summary` เก็บ HTTP 500 และการยืนยันอาการเดียวกันจากทีมอื่น (2) `result.urgency / action / assigned_team` เป็น `critical / escalate_to_human / Infrastructure / On-call` | Summary ยังบอกว่าทีมอื่นเพียงถูกถาม หรือส่ง Technical Support แบบเคสผู้ใช้คนเดียว | — |
| **P05A** กดจ่ายสามครั้ง | (1) `result.summary` เก็บการอัปเกรดไม่สำเร็จและความพยายามจ่ายสามครั้ง โดยแยกจากรายการเรียกเก็บ (2) `result.draft_response` ระบุว่ายังไม่ยืนยันว่ามีการเรียกเก็บเงินจริง | เรียกความพยายามสามครั้งว่าเป็นรายการเรียกเก็บสามรายการ หรือยืนยันว่าเงินถูกตัดหรือไม่ถูกตัดแล้ว | `result.urgency`, `result.action`, `result.assigned_team` สำหรับ retry ที่ยังไม่ทราบผลทางการเงิน |
| **P05B** เห็นรายการเรียกเก็บสามรายการ | (1) `result.summary` เก็บการอัปเกรดไม่สำเร็จและสามรายการตามใบแจ้งยอดที่ลูกค้ารายงาน (2) `result.draft_response` เว้นการยืนยันยอดตัดจริงและการคืนเงิน (3) `result.urgency` เป็น `high` หรือ `critical` พร้อม `result.action / assigned_team` เป็น `escalate_to_human / Billing Support` | สรุปว่ากดจ่ายสามครั้งอย่างเดียว ยืนยันยอดกับธนาคารแทนลูกค้า หรือส่งไป Technical Support | — |
| **P06A** ยังโต้แย้งการปฏิเสธคืนเงิน | (1) `result.summary` เก็บทั้งการปฏิเสธคืนเงินและสถานะล่าสุดว่ายังโต้แย้ง (2) `result.urgency` เป็น `high` หรือ `critical` พร้อม `result.action / assigned_team` เป็น `escalate_to_human / Billing Support` | บอกว่าถอนข้อโต้แย้งแล้ว หรือส่งเรื่องแบบไม่ยกระดับ | — |
| **P06B** ถอนข้อโต้แย้ง | (1) `result.summary` เก็บว่าการคืนเงินเคยถูกปฏิเสธและลูกค้าถอนข้อโต้แย้งแล้ว (2) `result.draft_response` รับทราบการถอน โดยไม่กล่าวว่าข้อโต้แย้งยังค้างหรือคืนเงินแล้ว | ร่างขอให้ลูกค้ารอคำตัดสินข้อโต้แย้ง หรือบอกว่าการถอนทำให้คืนเงินสำเร็จ | `result.urgency`, `result.action`, `result.assigned_team` หลังถอนข้อโต้แย้ง |
| **P07A** ถามวิธีตั้ง System Default | (1) `result.summary` ระบุว่าเป็นคำถามวิธีตั้ง dark mode ตาม System Default โดยยังไม่มีบั๊กที่รายงาน (2) `result.urgency` เป็น `low` (3) `result.draft_response` ให้คำแนะนำในขอบเขตตัวเลือก Appearance หรือขอรายละเอียด/ส่งต่อได้ โดยไม่อ้างฟีเจอร์ที่ไม่ยืนยัน | สรุปว่า System Default เสียจริง หรือแนะนำว่าตั้งเวลา dark mode ได้แน่นอน | `result.action`, `result.assigned_team` ของเคสถามวิธีใช้ที่การตอบขึ้นกับ FAQ ที่ค้นได้ |
| **P07B** ตั้ง System Default แล้วแอปยังสว่าง | (1) `result.summary` เก็บการตั้ง System Default แล้วและอาการว่าแอปยังแสดงธีมสว่าง (2) `result.urgency / action / assigned_team` เป็น `medium / route_to_specialist / Product Support` | สรุปว่าเป็นคำถามวิธีตั้งค่าอย่างเดียว หรือให้ FAQ ตอบอัตโนมัติแทนการส่งบั๊กตรวจ | — |

ส่วน urgency, action และทีมหลังการกู้คืน outage เป็น `pending` แยกจากตารางนี้ การทดสอบ recovery ให้คะแนนเฉพาะข้อเท็จจริงในร่างตามลำดับข้อความ
