/**
 * Design reminder — The Roastery Ledger:
 * Contemporary coffee-journal editorial design using oat paper, espresso ink,
 * Ember Orange accents, an asymmetric reading rail, and tactile, restrained motion.
 */
import { useState } from "react";
import {
  ArrowRight,
  Check,
  ChevronDown,
  Coffee,
  Menu,
  PackageCheck,
  Sparkles,
  X,
} from "lucide-react";

const plans = [
  {
    name: "จังหวะเบา",
    amount: "590",
    detail: "1 ถุง / เดือน · 200 กรัม",
    note: "สำหรับวันที่อยากเริ่มด้วยแก้วโปรด",
  },
  {
    name: "จังหวะพอดี",
    amount: "990",
    detail: "2 ถุง / เดือน · 400 กรัม",
    note: "สำหรับบ้านที่จริงจังกับเช้าของตัวเอง",
    featured: true,
  },
  {
    name: "จังหวะเต็ม",
    amount: "1,390",
    detail: "3 ถุง / เดือน · 600 กรัม",
    note: "สำหรับคนที่อยากให้ทั้งเดือนมีเรื่องให้ดื่ม",
  },
];

const notes = [
  { origin: "Kayanza, Burundi", taste: "พลัม · น้ำตาลทรายแดง · ชาดำ", roast: "Medium-light" },
  { origin: "Cajamarca, Peru", taste: "โกโก้ · อัลมอนด์ · ทอฟฟี่", roast: "Medium" },
  { origin: "Yirgacheffe, Ethiopia", taste: "มะลิ · พีช · น้ำผึ้ง", roast: "Light" },
];

function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export default function Home() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [chosenPlan, setChosenPlan] = useState("จังหวะพอดี");
  const [submitted, setSubmitted] = useState(false);

  const handlePlan = (plan: string) => {
    setChosenPlan(plan);
    scrollToSection("join");
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
  };

  return (
    <div className="min-h-screen overflow-x-hidden bg-[#f4efe5] text-[#281b17] selection:bg-[#c65a22] selection:text-white">
      <header className="fixed inset-x-0 top-0 z-50 border-b border-[#281b17]/10 bg-[#f4efe5]/92 backdrop-blur-xl">
        <div className="mx-auto flex h-[76px] max-w-[1440px] items-center justify-between px-5 sm:px-8 lg:px-12">
          <button
            aria-label="กลับสู่ด้านบน"
            className="flex items-center gap-3 text-left transition-opacity hover:opacity-70"
            onClick={() => scrollToSection("top")}
          >
            <img
              src="/manus-storage/roast-ritual-mark_02534a28.png"
              alt=""
              className="h-10 w-10 object-contain"
            />
            <span className="text-[11px] font-extrabold tracking-[0.18em] text-[#281b17]">ROAST &amp; RITUAL</span>
          </button>

          <nav className="hidden items-center gap-7 lg:flex" aria-label="เมนูหลัก">
            <button onClick={() => scrollToSection("how-it-works")} className="nav-link">วิธีทำงาน</button>
            <button onClick={() => scrollToSection("selection")} className="nav-link">กาแฟประจำเดือน</button>
            <button onClick={() => scrollToSection("plans")} className="nav-link">รูปแบบสมาชิก</button>
          </nav>

          <button onClick={() => scrollToSection("join")} className="hidden cta-button cta-button-sm sm:inline-flex">
            รับแก้วแรกของคุณ <ArrowRight size={15} />
          </button>

          <button
            aria-label={mobileOpen ? "ปิดเมนู" : "เปิดเมนู"}
            aria-expanded={mobileOpen}
            className="inline-flex h-10 w-10 items-center justify-center border border-[#281b17]/15 text-[#281b17] lg:hidden"
            onClick={() => setMobileOpen((open) => !open)}
          >
            {mobileOpen ? <X size={19} /> : <Menu size={19} />}
          </button>
        </div>
        {mobileOpen && (
          <div className="border-t border-[#281b17]/10 bg-[#f4efe5] px-5 py-5 lg:hidden">
            <div className="mx-auto grid max-w-[1440px] gap-1">
              {[
                ["วิธีทำงาน", "how-it-works"],
                ["กาแฟประจำเดือน", "selection"],
                ["รูปแบบสมาชิก", "plans"],
              ].map(([label, id]) => (
                <button
                  key={id}
                  onClick={() => {
                    scrollToSection(id);
                    setMobileOpen(false);
                  }}
                  className="flex items-center justify-between border-b border-[#281b17]/10 py-4 text-left text-lg font-medium"
                >
                  {label}<ArrowRight size={17} />
                </button>
              ))}
              <button
                onClick={() => {
                  scrollToSection("join");
                  setMobileOpen(false);
                }}
                className="mt-4 cta-button justify-center"
              >
                รับแก้วแรกของคุณ <ArrowRight size={16} />
              </button>
            </div>
          </div>
        )}
      </header>

      <main id="top">
        <section className="relative isolate border-b border-[#281b17]/10 pt-[76px]">
          <div className="paper-grain absolute inset-0 -z-10" />
          <div className="mx-auto grid min-h-[760px] max-w-[1440px] lg:grid-cols-[92px_minmax(0,1fr)_minmax(420px,0.83fr)]">
            <aside className="hidden border-r border-[#281b17]/10 lg:flex lg:flex-col lg:items-center lg:justify-between lg:py-11">
              <span className="vertical-label">SEASONAL COFFEE / 08.26</span>
              <div className="flex flex-col items-center gap-3">
                <span className="h-14 w-px bg-[#c65a22]" />
                <span className="font-display text-xl italic">01</span>
              </div>
            </aside>

            <div className="flex flex-col justify-between px-5 pb-10 pt-12 sm:px-8 sm:pb-12 sm:pt-20 lg:px-12 lg:pb-14 lg:pt-[102px]">
              <div className="max-w-[700px]">
                <div className="eyebrow mb-8">
                  <span className="h-2 w-2 rounded-full bg-[#c65a22]" />
                  CURATED COFFEE, AT YOUR PACE
                </div>
                <h1 className="font-display max-w-[690px] text-[clamp(3.4rem,7.3vw,7rem)] font-semibold leading-[0.86] tracking-[-0.065em] text-[#281b17]">
                  เช้าที่ดี<br />เริ่มจากเมล็ด<br /><em className="font-normal text-[#c65a22]">ที่เลือกอย่างตั้งใจ</em>
                </h1>
                <p className="mt-9 max-w-[510px] text-base leading-8 text-[#594842] sm:text-lg">
                  บอกจังหวะการดื่มของคุณ แล้วให้เราคัดกาแฟตามฤดูกาล คั่วสด และส่งถึงบ้านในวันที่คุณพร้อมหยุดเพื่อดื่มจริง ๆ
                </p>
                <div className="mt-10 flex flex-col items-start gap-4 sm:flex-row sm:items-center">
                  <button onClick={() => scrollToSection("join")} className="cta-button">
                    รับแก้วแรกของคุณ <ArrowRight size={17} />
                  </button>
                  <button onClick={() => scrollToSection("how-it-works")} className="text-link">
                    ดูวิธีที่เราคัด <span>↓</span>
                  </button>
                </div>
              </div>
              <div className="mt-14 flex max-w-[640px] items-start gap-4 border-t border-[#281b17]/15 pt-5 sm:gap-7">
                <span className="font-display text-3xl italic text-[#c65a22]">08</span>
                <p className="max-w-[410px] text-xs leading-6 text-[#594842] sm:text-sm">
                  การคัดเลือกเดือนนี้มาจากล็อตขนาดเล็กที่นักคั่วเลือกตามความสด รสชาติ และจังหวะของฤดูกาล—not จากสิ่งที่อยู่ในสต็อกนานที่สุด
                </p>
              </div>
            </div>

            <div className="relative min-h-[510px] overflow-hidden bg-[#d9c7af] lg:min-h-0">
              <img
                src="/manus-storage/roast-ritual-hero_76585d6c.jpg"
                alt="เซ็ตกาแฟคั่วพรีเมียมพร้อมถ้วยชิม"
                className="h-full w-full object-cover object-center"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-[#281b17]/45 via-transparent to-transparent" />
              <div className="absolute bottom-5 left-5 right-5 border border-white/30 bg-[#241713]/80 p-5 text-[#f5efe4] backdrop-blur-md sm:bottom-8 sm:left-8 sm:right-auto sm:w-[285px]">
                <div className="flex items-center justify-between text-[10px] font-bold tracking-[0.16em] text-[#f5efe4]/70">
                  <span>THIS MONTH</span><span>08 / 26</span>
                </div>
                <h2 className="mt-7 font-display text-3xl leading-none">Warm weather,<br />deep sweetness.</h2>
                <p className="mt-4 text-xs leading-5 text-[#f5efe4]/75">Burundi natural · plum · black tea · brown sugar</p>
              </div>
            </div>
          </div>
        </section>

        <section id="how-it-works" className="scroll-mt-20 bg-[#281b17] text-[#f5efe4]">
          <div className="mx-auto grid max-w-[1440px] lg:grid-cols-[92px_1fr]">
            <aside className="hidden border-r border-white/10 lg:flex lg:flex-col lg:items-center lg:justify-between lg:py-11">
              <span className="vertical-label text-[#f5efe4]/55">THE RITUAL / HOW IT WORKS</span>
              <div className="flex flex-col items-center gap-3">
                <span className="h-14 w-px bg-[#c65a22]" />
                <span className="font-display text-xl italic">02</span>
              </div>
            </aside>
            <div className="px-5 py-20 sm:px-8 sm:py-28 lg:px-12 lg:py-32">
              <div className="grid gap-12 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)] lg:gap-20">
                <div>
                  <div className="eyebrow text-[#f5efe4]/60"><span className="h-2 w-2 rounded-full bg-[#c65a22]" /> THREE SIMPLE MOVES</div>
                  <h2 className="font-display mt-8 max-w-[510px] text-5xl font-semibold leading-[0.93] tracking-[-0.045em] sm:text-6xl">
                    ไม่ใช่กล่องสุ่ม<br />แต่คือ <em className="text-[#e98452]">จังหวะ</em><br />ที่เลือกให้คุณ
                  </h2>
                </div>
                <div className="divide-y divide-white/15 border-t border-white/15">
                  {[
                    ["01", "บอกสิ่งที่คุณอยากดื่ม", "เลือกวิธีชง ระดับการคั่ว และความถี่ที่อยากให้กาแฟมาถึง"],
                    ["02", "เราจับคู่ล็อตตามฤดูกาล", "นักคั่วจับคู่คำตอบของคุณกับเมล็ดที่กำลังมีชีวิตชีวาที่สุดในช่วงนั้น"],
                    ["03", "เปิดซอง แล้วใช้เวลาสักครู่", "คุณจะได้รับโน้ตรสชาติและคำแนะนำสั้น ๆ เพื่อให้แก้วนั้นเป็นของคุณจริง ๆ"],
                  ].map(([no, title, detail]) => (
                    <div key={no} className="group grid grid-cols-[50px_1fr] gap-4 py-7 sm:grid-cols-[72px_1fr] sm:gap-7">
                      <span className="font-display text-2xl italic text-[#e98452]">{no}</span>
                      <div>
                        <h3 className="text-lg font-semibold sm:text-xl">{title}</h3>
                        <p className="mt-3 max-w-[420px] text-sm leading-6 text-[#f5efe4]/65">{detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="bg-[#e3d7c5]">
          <div className="mx-auto grid max-w-[1440px] lg:grid-cols-[92px_1.08fr_0.92fr]">
            <aside className="hidden border-r border-[#281b17]/10 lg:flex lg:flex-col lg:items-center lg:justify-between lg:py-11">
              <span className="vertical-label">FROM WHERE IT GROWS</span>
              <span className="font-display text-xl italic">03</span>
            </aside>
            <div className="min-h-[560px] overflow-hidden">
              <img src="/manus-storage/roast-ritual-origin_4427c3d5.jpg" alt="กาแฟเชอร์รีจากแหล่งปลูกบนพื้นที่สูง" className="h-full w-full object-cover" />
            </div>
            <div className="flex flex-col justify-center px-5 py-20 sm:px-8 lg:px-12 lg:py-12">
              <div className="eyebrow"><span className="h-2 w-2 rounded-full bg-[#c65a22]" /> FIRST, LISTEN TO THE LAND</div>
              <h2 className="font-display mt-8 text-5xl font-semibold leading-[0.95] tracking-[-0.045em] sm:text-6xl">เราไม่เร่งกาแฟ<br />ให้ทัน <em className="text-[#c65a22]">กำหนด</em></h2>
              <p className="mt-7 max-w-[420px] leading-8 text-[#594842]">ทุกล็อตเริ่มจากความพร้อมของผลผลิต ไม่ใช่ปฏิทินการตลาด เรามองหาความหวานที่ชัด ความสะอาดของแก้ว และเรื่องราวที่คุณอยากกลับมาดื่มซ้ำ</p>
              <div className="mt-9 border-t border-[#281b17]/15 pt-5">
                <p className="text-[11px] font-bold tracking-[0.15em] text-[#7a655a]">OUR BUYING NOTES</p>
                <p className="mt-3 font-display text-2xl italic leading-tight">“ความโดดเด่นไม่ควรดังเกินไป—มันควรจำได้”</p>
              </div>
            </div>
          </div>
        </section>

        <section id="selection" className="scroll-mt-20 border-y border-[#281b17]/10 bg-[#f4efe5]">
          <div className="mx-auto grid max-w-[1440px] lg:grid-cols-[92px_1fr]">
            <aside className="hidden border-r border-[#281b17]/10 lg:flex lg:flex-col lg:items-center lg:justify-between lg:py-11">
              <span className="vertical-label">THE MONTHLY SELECTION</span>
              <span className="font-display text-xl italic">04</span>
            </aside>
            <div className="px-5 py-20 sm:px-8 lg:px-12 lg:py-28">
              <div className="flex flex-col justify-between gap-7 border-b border-[#281b17]/15 pb-9 md:flex-row md:items-end">
                <div>
                  <div className="eyebrow"><span className="h-2 w-2 rounded-full bg-[#c65a22]" /> OPEN THE ROAST NOTE</div>
                  <h2 className="font-display mt-7 text-5xl font-semibold leading-[0.92] tracking-[-0.05em] sm:text-6xl">สามรสชาติ<br />ที่เราอยากเล่า</h2>
                </div>
                <p className="max-w-[310px] text-sm leading-6 text-[#594842]">ไม่มีคำอธิบายยาวเกินจำเป็น มีเพียงโน้ตที่ช่วยให้คุณรู้ว่าจะมองหาอะไรในแก้วต่อไป</p>
              </div>
              <div className="mt-8 grid gap-0 border-l border-t border-[#281b17]/15 md:grid-cols-3">
                {notes.map((item, index) => (
                  <article key={item.origin} className="group min-h-[238px] border-b border-r border-[#281b17]/15 p-6 transition-colors duration-200 hover:bg-[#ede3d4] sm:p-8">
                    <div className="flex items-start justify-between">
                      <span className="font-display text-3xl italic text-[#c65a22]">0{index + 1}</span>
                      <Coffee size={18} strokeWidth={1.5} className="text-[#281b17]/55" />
                    </div>
                    <h3 className="mt-12 text-base font-bold">{item.origin}</h3>
                    <p className="mt-3 font-display text-xl leading-tight">{item.taste}</p>
                    <p className="mt-5 text-[11px] font-bold tracking-[0.12em] text-[#7a655a]">{item.roast.toUpperCase()} ROAST</p>
                  </article>
                ))}
              </div>
              <div className="mt-8 overflow-hidden bg-[#d2baa1]">
                <img src="/manus-storage/roast-ritual-collection_aaf8e3a6.jpg" alt="คอลเลกชันกาแฟรายเดือนพร้อมอุปกรณ์ชง" className="h-[360px] w-full object-cover sm:h-[460px]" />
              </div>
            </div>
          </div>
        </section>

        <section id="plans" className="scroll-mt-20 bg-[#f4efe5]">
          <div className="mx-auto grid max-w-[1440px] lg:grid-cols-[92px_1fr]">
            <aside className="hidden border-r border-[#281b17]/10 lg:flex lg:flex-col lg:items-center lg:justify-between lg:py-11">
              <span className="vertical-label">FIND YOUR PACE</span>
              <span className="font-display text-xl italic">05</span>
            </aside>
            <div className="px-5 py-20 sm:px-8 lg:px-12 lg:py-28">
              <div className="grid gap-8 lg:grid-cols-[0.75fr_1.25fr] lg:items-end">
                <div>
                  <div className="eyebrow"><span className="h-2 w-2 rounded-full bg-[#c65a22]" /> MEMBERSHIP, WITHOUT THE NOISE</div>
                  <h2 className="font-display mt-8 text-5xl font-semibold leading-[0.92] tracking-[-0.05em] sm:text-6xl">เลือกกาแฟ<br />ให้พอดีกับ<br /><em className="text-[#c65a22]">ชีวิตจริง</em></h2>
                </div>
                <p className="max-w-[420px] text-base leading-8 text-[#594842] lg:ml-auto">เลือกแผน เปลี่ยนจังหวะ หรือพักไว้ก่อนเมื่อคุณต้องการ ไม่มีสัญญาที่ยาวกว่าความตั้งใจจะดื่มกาแฟดี ๆ ของคุณ</p>
              </div>
              <div className="mt-14 grid gap-4 lg:grid-cols-3">
                {plans.map((plan) => (
                  <article key={plan.name} className={`relative flex min-h-[350px] flex-col border p-6 sm:p-7 ${plan.featured ? "border-[#c65a22] bg-[#c65a22] text-white" : "border-[#281b17]/15 bg-[#eee6d9]"}`}>
                    {plan.featured && <span className="absolute right-5 top-5 text-[10px] font-bold tracking-[0.15em] text-white/75">MOST LOVED PACE</span>}
                    <div>
                      <p className={`text-[11px] font-bold tracking-[0.15em] ${plan.featured ? "text-white/70" : "text-[#7a655a]"}`}>MONTHLY MEMBERSHIP</p>
                      <h3 className="font-display mt-7 text-4xl italic">{plan.name}</h3>
                      <p className={`mt-5 text-sm leading-6 ${plan.featured ? "text-white/75" : "text-[#594842]"}`}>{plan.note}</p>
                    </div>
                    <div className="mt-auto border-t border-current/20 pt-5">
                      <p className="font-display text-4xl leading-none">฿{plan.amount}</p>
                      <p className={`mt-3 text-xs ${plan.featured ? "text-white/75" : "text-[#594842]"}`}>{plan.detail}</p>
                      <button onClick={() => handlePlan(plan.name)} className={`mt-6 flex items-center gap-2 text-sm font-bold underline-offset-4 hover:underline ${plan.featured ? "text-white" : "text-[#281b17]"}`}>
                        เลือกแผนนี้ <ArrowRight size={16} />
                      </button>
                    </div>
                  </article>
                ))}
              </div>
              <p className="mt-6 text-xs leading-5 text-[#7a655a]">ราคาและรายการนี้เป็นตัวอย่างสำหรับหน้าสาธิต สามารถปรับให้สอดคล้องกับสินค้าจริงและระบบชำระเงินของคุณได้ภายหลัง</p>
            </div>
          </div>
        </section>

        <section className="bg-[#d9c7af]">
          <div className="mx-auto grid max-w-[1440px] lg:grid-cols-[92px_0.86fr_1.14fr]">
            <aside className="hidden border-r border-[#281b17]/10 lg:flex lg:flex-col lg:items-center lg:justify-between lg:py-11">
              <span className="vertical-label">BREW IT YOUR WAY</span>
              <span className="font-display text-xl italic">06</span>
            </aside>
            <div className="order-2 flex flex-col justify-center px-5 py-20 sm:px-8 lg:order-1 lg:px-12">
              <div className="eyebrow"><span className="h-2 w-2 rounded-full bg-[#c65a22]" /> YOUR RITUAL, YOUR METHOD</div>
              <h2 className="font-display mt-8 text-5xl font-semibold leading-[0.93] tracking-[-0.05em] sm:text-6xl">หนึ่งซอง<br />หลายวิธี<br />แต่ <em className="text-[#c65a22]">แก้วเดียวกัน</em></h2>
              <ul className="mt-9 space-y-4 text-sm text-[#594842]">
                {["เลือกเมล็ดหรือบดตามอุปกรณ์ที่คุณใช้", "รับโน้ตชงสั้น ๆ สำหรับ pour-over, espresso หรือ French press", "ให้รสชาติของล็อตใหม่เป็นจุดเริ่มต้น ไม่ใช่กติกาตายตัว"].map((text) => (
                  <li key={text} className="flex gap-3 leading-6"><Check size={16} className="mt-1 shrink-0 text-[#c65a22]" />{text}</li>
                ))}
              </ul>
            </div>
            <div className="order-1 min-h-[480px] overflow-hidden lg:order-2">
              <img src="/manus-storage/roast-ritual-brew_6f3aa086.jpg" alt="การชง pour-over อย่างพิถีพิถัน" className="h-full w-full object-cover" />
            </div>
          </div>
        </section>

        <section id="join" className="scroll-mt-20 bg-[#281b17] text-[#f5efe4]">
          <div className="mx-auto grid max-w-[1440px] lg:grid-cols-[92px_1fr]">
            <aside className="hidden border-r border-white/10 lg:flex lg:flex-col lg:items-center lg:justify-between lg:py-11">
              <span className="vertical-label text-[#f5efe4]/55">YOUR FIRST CUP STARTS HERE</span>
              <span className="font-display text-xl italic">07</span>
            </aside>
            <div className="px-5 py-20 sm:px-8 lg:px-12 lg:py-28">
              <div className="grid gap-14 lg:grid-cols-[1fr_0.83fr] lg:gap-24">
                <div>
                  <div className="eyebrow text-[#f5efe4]/60"><span className="h-2 w-2 rounded-full bg-[#c65a22]" /> YOUR NEXT MONTH BEGINS NOW</div>
                  <h2 className="font-display mt-8 max-w-[700px] text-6xl font-semibold leading-[0.88] tracking-[-0.06em] sm:text-7xl">พร้อมให้กาแฟ<br />ดี ๆ <em className="text-[#e98452]">เข้ามา</em><br />ในทุกเช้าไหม</h2>
                  <div className="mt-10 flex items-center gap-4 text-sm text-[#f5efe4]/65"><PackageCheck size={20} className="text-[#e98452]" /><span>เลือกไว้แล้ว: <strong className="font-semibold text-[#f5efe4]">{chosenPlan}</strong></span></div>
                </div>
                <div className="border border-white/20 bg-white/[0.06] p-6 backdrop-blur-sm sm:p-8">
                  {submitted ? (
                    <div className="flex min-h-[280px] flex-col justify-center">
                      <Sparkles className="text-[#e98452]" size={28} />
                      <h3 className="font-display mt-7 text-4xl leading-none">บันทึกความสนใจ<br />ของคุณแล้ว</h3>
                      <p className="mt-5 max-w-[370px] text-sm leading-6 text-[#f5efe4]/65">ขอบคุณที่ให้ Roast &amp; Ritual เป็นส่วนหนึ่งของเช้าถัดไป ในเว็บไซต์จริง ขั้นตอนนี้สามารถเชื่อมต่อกับระบบเก็บรายชื่อหรือ checkout ได้</p>
                    </div>
                  ) : (
                    <form onSubmit={handleSubmit}>
                      <p className="text-[11px] font-bold tracking-[0.15em] text-[#f5efe4]/55">BEGIN WITH A NOTE</p>
                      <h3 className="font-display mt-4 text-3xl">ให้เราส่งรายละเอียดรอบแรกถึงคุณ</h3>
                      <label className="mt-8 block text-xs font-bold tracking-[0.1em] text-[#f5efe4]/70" htmlFor="email">อีเมลของคุณ</label>
                      <input id="email" required type="email" placeholder="you@example.com" className="mt-3 w-full border-b border-white/35 bg-transparent px-0 py-3 text-base outline-none placeholder:text-[#f5efe4]/30 focus:border-[#e98452]" />
                      <label className="mt-7 block text-xs font-bold tracking-[0.1em] text-[#f5efe4]/70" htmlFor="method">วิธีชงที่ใช้บ่อย</label>
                      <div className="relative">
                        <select id="method" defaultValue="pour-over" className="mt-3 w-full appearance-none border-b border-white/35 bg-transparent px-0 py-3 pr-8 text-base outline-none focus:border-[#e98452]">
                          <option className="bg-[#281b17]" value="pour-over">Pour-over</option>
                          <option className="bg-[#281b17]" value="espresso">Espresso</option>
                          <option className="bg-[#281b17]" value="french-press">French press</option>
                          <option className="bg-[#281b17]" value="other">ยังเลือกไม่แน่ใจ</option>
                        </select>
                        <ChevronDown className="pointer-events-none absolute bottom-4 right-0" size={16} />
                      </div>
                      <button type="submit" className="mt-9 cta-button w-full justify-center">รับรายละเอียดรอบแรก <ArrowRight size={17} /></button>
                      <p className="mt-4 text-center text-[11px] leading-5 text-[#f5efe4]/45">ไม่มีสแปม มีเพียงเรื่องของกาแฟและรอบจัดส่งที่เกี่ยวข้องกับคุณ</p>
                    </form>
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="bg-[#1d1310] text-[#f5efe4]/65">
        <div className="mx-auto flex max-w-[1440px] flex-col justify-between gap-9 px-5 py-10 sm:px-8 lg:flex-row lg:items-end lg:px-12">
          <div className="flex items-center gap-3"><img src="/manus-storage/roast-ritual-mark_02534a28.png" alt="" className="h-11 w-11 object-contain" /><span className="text-[11px] font-extrabold tracking-[0.18em] text-[#f5efe4]">ROAST &amp; RITUAL</span></div>
          <p className="max-w-[390px] text-xs leading-5 lg:text-right">ตัวอย่างแลนดิ้งเพจสำหรับบริการสมัครสมาชิกกาแฟพรีเมียม สร้างเพื่อสาธิตรูปแบบเนื้อหาและประสบการณ์การตัดสินใจ</p>
        </div>
      </footer>
    </div>
  );
}
