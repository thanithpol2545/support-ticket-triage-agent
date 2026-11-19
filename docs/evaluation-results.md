# OOCA Evaluation สำหรับผู้ตรวจ

ตรวจวันที่ 19 พฤศจิกายน 2026 ที่ baseline `aacbe28bc92b352ee59e1bcff76b7013844386ba` ซึ่งมี tree ตรงกับ `origin/main` ที่ `9c2114ac46680bd81f8382d9bea3cf4c542a66f8` ผลหลังแก้วัดจาก working tree ที่ส่งมอบบน baseline นี้ การประมวลผลจริงยังใช้ GPT ผ่าน OpenAI Responses API

**Offline ล่าสุดผ่าน 202 tests** บน Python 3.11 รวมการทดสอบ audit ผ่าน CLI ทั้งสองแบบกับ Responses API จำลอง และการตรวจตัวประเมินด้วยผลที่กำหนดเอง รอบแรกผ่าน 153 tests ส่วน **GPT end-to-end เป็น NOT VERIFIED** เพราะสภาพแวดล้อมไม่มี `OPENAI_API_KEY` ที่ได้รับอนุญาต CLI คืน exit code 2 และไม่สร้างไฟล์ผล

## 1. สาม ticket ต้นฉบับของ OOCA

| Ticket | Expected urgency / action / team | Baseline → หลังแก้ผ่าน CLI จำลอง | GPT live |
|---|---|---|---|
| TICKET-001 | `high / escalate_to_human / Billing Support` | ตรง → ตรง | ยังไม่ได้รัน |
| TICKET-002 | `critical / escalate_to_human / Infrastructure / On-call` | ตรง → ตรง | ยังไม่ได้รัน |
| TICKET-003 | `medium / route_to_specialist / Product Support` | ตรง → ตรง | ยังไม่ได้รัน |

## 2. เก้า edge fixtures

| Metric ใน CLI จำลอง | Baseline | หลังแก้ | GPT live |
|---|---:|---:|---|
| Urgency ตรงกับ expected | 9/9 | 9/9 | ยังไม่ได้รัน |
| Action ตรงกับ expected | 6/6 | 6/6 | ยังไม่ได้รัน |
| History และ KB เรียกสำเร็จ | 9/9 | 9/9 | ยังไม่ได้รัน |

ในสามแถวที่ `expected_action` เป็น `null` fixture ไม่กำหนด action ที่ต้องตรง [เก้า fixtures](../evaluation/adversarial_cases.json)

## 3. ชุดพัฒนาและ regression 24 เคส A/B

| คู่ | สิ่งที่ตรวจ | Baseline A / B | หลังแก้ A / B |
|---|---|---|---|
| P01 | คำถามสมมติ / เหตุจริงที่ลงท้ายด้วยคำถาม | ตก / ผ่าน | ผ่าน / ผ่าน |
| P02 | ยังล่ม / แจ้งว่ากู้คืน | ผ่าน / ตก | ผ่าน / ผ่าน |
| P03 | กู้คืนและยังใช้งานได้ / ล่มซ้ำ | ตก / ผ่าน | ผ่าน / ผ่าน |
| P04 | ถามขอบเขต / ยืนยันว่าทีมอื่นเจอด้วย | ยังไม่ได้วัด | พร้อม Ticket และ [เกณฑ์ราย A/B](paired-scoring-rubric.md) |
| P05 | ลองจ่ายหลายครั้ง / เห็นหลายรายการเรียกเก็บ | ยังไม่ได้วัด | พร้อม Ticket และเกณฑ์ราย A/B |
| P06 | ยังโต้แย้ง / ถอนข้อโต้แย้ง | ยังไม่ได้วัด | พร้อม Ticket และเกณฑ์ราย A/B |
| P07 | ขอวิธีตั้งค่า / แจ้งบั๊ก System Default | ยังไม่ได้วัด | พร้อม Ticket และเกณฑ์ราย A/B |
| P08 | GPT จำลองขอรหัสผ่าน / เตือนว่าอย่าส่ง | ตก / ผ่าน | ผ่าน / ผ่าน |
| P09 | Retrieval สำนวนอังกฤษเรื่องจ่ายซ้ำ | พบ / พลาด | พบ / พลาด |
| P10 | Retrieval โหมดมืดไทย / ไทยปนอังกฤษ | พลาด / พบ | พลาด / พบ |
| P11 | Retrieval แจ้งเตือน / โหมดมืด | เจอบทความผิดหัวข้อ / พบ | เจอบทความผิดหัวข้อ / พบ |
| P12 | Public status `operational` / `degraded` เมื่อผู้ใช้ยืนยันว่าเกิดเหตุ | ผ่าน / ผ่าน | ผ่าน / ผ่าน |

P01A เคยถูกยกระดับเป็น `critical / escalate_to_human` P02B และ P03A เคยได้ร่างว่าผู้ใช้ยังเข้าไม่ได้ และ P08A เคยได้ร่างที่ขอรหัสผ่าน หลังแก้กฎจะพิจารณาสถานะล่าสุดที่ยืนยันไว้และแทนร่างที่ขอรหัสผ่านตรง ๆ ด้วยร่างปลอดภัย เคสที่รายงานว่ากู้คืนแล้วตรวจเฉพาะข้อความร่าง การติดตามยังใช้เส้นทางเดิมระหว่างรอ Support ตกลงเกณฑ์ urgency และทีม กฎจับรูปประโยคเป็น deterministic backstop และยังไม่มีหลักฐานว่าครอบคลุมทุกสำนวน [ข้อความ A/B](../evaluation/paired_cases.json) · [เทสต์ผ่าน CLI](../tests/test_paired_regression.py)

### ตรวจซ้ำตามผลรีวิว PR #5

ชุดนี้ใช้ข้อเสนอจำลองจาก OpenAI แล้วตรวจทั้ง `proposal` และ `result` ใน `--audit` เดียวกัน แต่ละแถวใช้เทสต์ชุดเดียวกันเทียบก่อนและหลังแก้

| Policy ก่อนแก้ | ผลก่อนแก้ | ผลหลังแก้ |
| --- | --- | --- |
| `cdef161` | ตก 4 / ผ่าน 8 | ผ่าน 12/12 บน `ecf480a` |
| `ecf480a` | ตก 5 / ผ่าน 14 | ผ่าน 19/19 บน `af77181` |
| `af77181` | ตก 5 / ผ่าน 20 | ผ่าน 25/25 บน `75eb622` |
| `75eb622` | ตก 6 / ผ่าน 29 | ผ่าน 35/35 บน `2ac71d2` |
| `2ac71d2` | ตก 6 / ผ่าน 40 | ผ่าน 46/46 บน `be96081` |
| `be96081` | ตก 3 / ผ่าน 46 | ผ่าน 49/49 ล่าสุด |

| เคส | ก่อนแก้ | หลังแก้ |
| --- | --- | --- |
| `Please provide us with your password.` | ร่างส่งต่อยังขอรหัสผ่านทั้ง specialist และ human escalation ทางตอบอัตโนมัติใช้ FAQ ที่อนุมัติแล้ว | ร่างสุดท้ายปลอดภัยครบสาม action และคง action กับทีมที่เสนอไว้ในเคสส่งต่อ |
| `Please never share your password.` | ผ่านในร่างส่งต่อ | คงคำเตือนเดิมทั้ง specialist และ human escalation |
| Asia เข้าไม่ได้ แล้ว Europe แจ้งว่ากลับเข้าได้ | ร่างยืนยันการกู้คืนแบบไม่ระบุขอบเขต | ร่างระบุว่าได้รับรายงานว่า Europe กลับเข้าได้ และการกู้คืนใน Asia ยังไม่ยืนยัน |
| Asia ยืนยันว่ากู้คืนเอง / Asia กู้คืนแล้วล่มซ้ำ | ทั้งสองเคสควบคุมสื่อสถานะล่าสุดถูกต้อง | ร่างสื่อการกู้คืนและการล่มซ้ำตามลำดับข้อความ เกณฑ์ urgency หลังการกู้คืนเป็น `pending` |
| `If the service is down, all users cannot log in. What is the procedure?` | Policy ยกระดับเป็น `critical / escalate_to_human` | คงข้อเสนอจำลอง `low / route_to_specialist` |
| `All users cannot log in. What is the procedure?` | ผ่าน | ยังยกระดับเป็น `critical / escalate_to_human` ไป Infrastructure / On-call |
| `Could you confirm your account password so we can update your email?` | หลุดในร่างส่งต่อทั้งสอง action บน `ecf480a` | แทนด้วยคำเตือนและคง action กับทีมที่เสนอ |
| พนักงานใน Thailand เข้าไม่ได้ แล้วพนักงานใน Germany กลับเข้าได้ | ร่างยืนยันการกู้คืนแบบไม่ระบุขอบเขตบน `ecf480a` | ระบุว่า Germany กลับเข้าได้ และการกู้คืนใน Thailand ยังไม่ยืนยัน |
| Asia และ Europe ต่างยืนยันว่ากู้คืนแล้ว ต่อมา Europe แจ้ง HTTP 500 อีก | บน `ecf480a` ร่างระบุเพียงว่ายังไม่ยืนยันการกู้คืนใน Europe | ร่างเก็บการกู้คืนใน Asia และบอกว่ารายงานล่าสุดจาก Europe คือเข้าใช้งานไม่ได้ |
| `All users in Asia get HTTP 500 right now and I need to know if there is a runbook.` | `ecf480a` คงข้อเสนอ `low / route_to_specialist` ผิด | ยกระดับเป็น `critical / escalate_to_human` ไป Infrastructure / On-call ส่วน `All users get HTTP 500 if the service is down.` ยังคงเป็นกรณีสมมติ |
| `What is the password you use to sign in?` | `af77181` ส่งคำถามขอรหัสผ่านผ่านทั้งสอง action ส่งต่อ | ใช้ร่างเตือนเรื่องความปลอดภัยและคง action กับทีม |
| `In Singapore all employees cannot sign in.` แล้ว `In Japan all staff can sign in again.` | `af77181` รายงานการกู้คืนโดยรวม | ร่างระบุว่ากู้คืนใน Japan และยังไม่ยืนยันการกู้คืนใน Singapore ทั้งแบบมีและไม่มีจุลภาคหลังชื่อพื้นที่ |
| `All users in Europe are getting HTTP 500 right now and please let me know if I should page on-call.` | `af77181` ข้ามรายงานเหตุเพราะคำถามส่วนท้ายมี `if` | คงรายงาน HTTP 500 เป็นเหตุจริงและยกระดับไป Infrastructure / On-call |
| `May I have your account password so I can troubleshoot?` และ `Reset your password. Then send it to us.` | `75eb622` ส่งทั้งสองข้อความผ่าน specialist และ human escalation | ใช้ร่างเตือนและคง action กับทีม คำเตือนตรง ๆ และคำแนะนำให้รีเซ็ตในบัญชีด้วยตนเองยังคงอยู่ในเคสควบคุม |
| `Singapore: all employees cannot sign in.` แล้ว `Japan: all staff can sign in again.` | `75eb622` ยืนยันกู้คืนแบบรวม | ร่างระบุว่า Japan กลับเข้าได้ สถานะการกู้คืนใน Singapore ยังไม่ยืนยัน |
| `All users in Europe get HTTP 500 and please advise if we should page on-call.` | `75eb622` คง `low / route_to_specialist` ผิด | แยกรายงานเหตุออกจากคำขอให้แนะนำขั้นตอนและยกระดับไป Infrastructure / On-call |
| `Reset your password. Then email it to our support team.` และ `Never share your password, except with support.` | `2ac71d2` ส่งทั้งสองร่างผ่าน specialist และ human escalation | ร่างที่กล่าวถึงรหัสผ่านคงได้เมื่อทุกประโยคเป็นคำเตือนหรือคำแนะนำจัดการรหัสผ่านด้วยตนเองที่ Policy รองรับ กรณีอื่นใช้คำเตือนมาตรฐานและคง action กับทีม |
| `Cebu office: currently all staff cannot sign in.` แล้ว `Taipei office: now all staff can sign in again.` | `2ac71d2` ยืนยันการกู้คืนแบบรวม | ร่างแยกว่า Taipei กลับเข้าได้และยังไม่ยืนยันการกู้คืนของ Cebu |
| `All users in Europe are getting HTTP 500 right now - can you check if we should page on-call?` | `2ac71d2` หลุดการยกระดับ | รายงานเหตุจริงก่อนขีดถูกยกระดับ ส่วนเงื่อนไข `If the system goes down — all staff cannot log in.` ไม่เข้าเกณฑ์ |
| สำนักงาน Jakarta และ Seoul ระบุพื้นที่คนละบรรทัดกับข้อความรายงาน | `be96081` ตีความการกู้คืนใน Seoul ว่าผู้ใช้กลับเข้าได้โดยรวม | ใช้หัวข้อสำนักงานกำกับบรรทัดรายงาน ร่างยืนยันเฉพาะ Seoul และเว้นการกู้คืน Jakarta ไว้ |
| `All users in Asia get HTTP 500 — if the service goes down.` และสำนวน `, but only if …` | `be96081` ยกระดับรายงานสมมติ | อ่านเงื่อนไขส่วนท้ายคู่กับข้อความก่อนขีดหรือจุลภาค ส่วนรายงานเหตุจริงที่ตามด้วยคำถามยังยกระดับ |

รันซ้ำด้วย `python -m pytest -q tests/test_paired_regression.py -k audit` เกณฑ์ P04–P07 มี **18 ข้อที่ประเมินได้** โดยตัด field ที่เป็น `pending` ออกจากตัวส่วน ยังไม่มีการให้คะแนนจาก GPT จริง [เกณฑ์ให้คะแนนราย A/B](paired-scoring-rubric.md)

### Retrieval probes จากข้อความลูกค้าตรง ๆ

| Case | Query | FAQ คาดหวัง | Top 3 จริงตามลำดับ |
|---|---|---|---|
| P09A | I got a duplicate charge after trying to switch plans. | KB-001 | KB-001 |
| P09B | I got billed twice after trying to switch plans. | KB-001 | ว่าง |
| P10A | ขอวิธีตั้งโหมดมืดหน่อยครับ | KB-003 | ว่าง |
| P10B | ขอวิธีตั้ง dark mode หน่อยครับ | KB-003 | KB-003 |
| P11A | ช่วยชี้หน้า settings ของการแจ้งเตือนหน่อยครับ | ไม่มี FAQ ตรงหัวข้อ | KB-003 จากคำว่า `settings` |
| P11B | ช่วยชี้หน้า settings ของโหมดมืดหน่อยครับ | KB-003 | KB-003 |

`hit@3` เท่ากับ **3/5** สำหรับเคสที่มี FAQ กำกับ P11A ยังได้ `KB-003` ผิดหัวข้อและไม่นับในตัวส่วน ใน CLI จำลอง ทั้ง `settings` และ `settings help` ถอด citation และคำแนะนำ Appearance ออกจากผลสุดท้าย เส้นทางแรกส่งต่อ ส่วนเส้นทางที่มี `KB-004` ใช้ FAQ ขอรายละเอียดทั่วไป Retrieval และ KB ใช้ชุดเดิม คำค้นจาก GPT จริงยังไม่มีผล

## 4. BANKING77 pilot

สร้างซ้ำได้ 16 แถวจาก `test` revision `57ec275d8078af65b7731c2a98be812d844a6d6b` ตรวจ SHA-256 ของ CSV และเทียบข้อความ ลำดับ และ Ticket JSON ที่จัดส่งแล้ว ต้นทางอนุญาตเผยแพร่ภายใต้ CC BY 4.0 เครดิตและรายละเอียดการคัดเลือกอยู่ใน [รายงานแหล่งข้อมูล](external-evaluation-pilot.md) · [ใบอนุญาตต้นทาง](https://github.com/PolyAI-LDN/task-specific-datasets/blob/57ec275d8078af65b7731c2a98be812d844a6d6b/LICENSE)

| Source intent | พร้อมให้คะแนน | Pending | ถูก / ให้คะแนนแล้ว |
|---|---:|---|---|
| `card_payment_fee_charged` | 4 | — | — / 0 |
| `card_payment_not_recognised` | 4 | — | — / 0 |
| `declined_card_payment` | 3 | `B77-TEST-1815` ระบุเพียงว่าจ่ายไม่ได้ | — / 0 |
| `pending_card_payment` | 3 | `B77-TEST-1604` ถามวิธีทำรายการให้เสร็จโดยไม่บอกสถานะ | — / 0 |
| **รวม** | **14** | **2** | **— / 0** |

ล็อก `banking77-issue-types-v1` ก่อนเห็นผล GPT โดยใช้ label ต้นทางกับรายการคำพ้องที่ระบุไว้ เทียบทั้งค่าหลัง normalize Unicode, ตัวพิมพ์ และตัวคั่น ตัวประเมินคืนจำนวนถูกและจำนวนที่ให้คะแนนแยกตาม intent พร้อม `expected` และ `actual` ของทุกเคสที่ผิด แสดงผลที่ขาดและ pending แยกกัน คำกว้างอย่าง `billing` อย่างเดียวไม่ตรงเกณฑ์ และชุดนี้ไม่มีเฉลย urgency, action หรือ routing [rubric และตัวประเมิน](../evaluation/banking77.py)

## วิธีรันซ้ำ

จาก root ของ checkout หลังติดตั้ง dependencies สำหรับทดสอบ

```powershell
python -m pip install -e '.[dev]'
git rev-parse HEAD origin/main
python -m pytest -q
python -m triage_agent --help
triage-agent --help
python -m evaluation.banking77 verify
python -m evaluation.paired probe
```

`verify` ดาวน์โหลดจาก revision ที่ล็อกไว้ ใช้ `--source <test.csv>` ถ้ามีไฟล์ต้นทางอยู่แล้ว ใช้ `--output <regenerated.json>` เพื่อบันทึก snapshot ที่สร้างซ้ำหลังตรวจว่าตรงกัน คำสั่ง PowerShell ด้านล่างโหลด Policy ของ `be96081` แล้ว replay เทสต์ล่าสุดเพื่อได้ผล **3 ตก / 46 ผ่าน** สำหรับแถวก่อนหน้าให้ใช้ชุดเทสต์บน SHA ในคอลัมน์หลังแก้และตั้ง `revision` เป็น SHA ในคอลัมน์ก่อนแก้ ส่วนผลก่อนแก้รอบแรกของ P01–P03, P08 และ P12 ใช้ `aacbe28bc92b352ee59e1bcff76b7013844386ba` และเลือก `-k "not audit"`

```powershell
@'
import subprocess
from types import ModuleType

import pytest
from triage_agent import agent

revision = "be96081563e44942220af1f59f7b42fcba1fd468"
path = "src/triage_agent/policy.py"
baseline = ModuleType("triage_agent.baseline_policy")
source = subprocess.check_output(["git", "show", f"{revision}:{path}"])
exec(compile(source, f"{revision}:{path}", "exec"), baseline.__dict__)
agent.finalize = baseline.finalize
raise SystemExit(pytest.main(["-q", "tests/test_paired_regression.py", "-k", "audit"]))
'@ | python -
```

เมื่อมี key ที่อนุญาตให้ใช้ ตาม [วิธีตั้ง key](../README.md#openai-key-and-model) ให้รันผ่าน CLI โดยใช้โฟลเดอร์ใหม่ต่อรอบเพื่อเก็บหลักฐานทั้งสี่ชุดแยกกัน

```powershell
$run = (New-Item -Type Directory -Path (Join-Path ([System.IO.Path]::GetTempPath()) ("ooca-eval-" + [guid]::NewGuid()))).FullName
git rev-parse HEAD | Set-Content "$run/commit.txt"
python -m evaluation.paired prepare-edges --output "$run/edges.json"
python -m evaluation.paired prepare --output "$run/pairs.json"
python -m evaluation.banking77 prepare --output "$run/banking77.json"

python -m triage_agent --all --audit --output "$run/ooca-audit.json"
python -m triage_agent --ticket-file "$run/edges.json" --audit --output "$run/edges-audit.json"
python -m triage_agent --ticket-file "$run/pairs.json" --audit --output "$run/pairs-audit.json"
python -m triage_agent --ticket-file "$run/banking77.json" --audit --output "$run/banking77-audit.json"

python -m evaluation.paired model-queries "$run/pairs-audit.json"
python -m evaluation.banking77 score "$run/banking77-audit.json" --output "$run/banking77-scores.json"
```

ชุด live สำหรับ A/B มี 20 Ticket ที่ต่างกันด้วยข้อความลูกค้า P08 และ P12 ใช้ผลควบคุมที่บังคับจากเทสต์ offline ให้เทียบ `proposal` กับ `result` ใน audit เดียวกัน และดู `result.tool_trace` สำหรับคำค้นที่ GPT สร้าง แยกจากตารางคำค้นตรง ๆ Audit เก็บข้อเสนอและข้อมูลเครื่องมือฉบับเต็มสำหรับผู้ตรวจ

เคสที่เปิดเฉลยและใช้ตรวจหรือแก้โค้ดเป็น regression การประเมินกับเคสใหม่ควรใช้ holdout ที่ล็อกข้อความ เฉลย และเกณฑ์ก่อนรัน เก็บเคสคู่และสำนวนของเหตุการณ์เดียวกันไว้ฝั่งเดียวกัน
