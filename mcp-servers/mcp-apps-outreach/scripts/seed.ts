/**
 * Generates `data/outreach.json`: a deterministic B2B outbound dataset.
 *
 * Every random choice comes from one PRNG with a fixed seed and every date is
 * relative to a fixed `AS_OF`, so running the script twice yields the same file.
 */
import fs from "node:fs/promises";
import path from "node:path";
import type {
  Account,
  Campaign,
  Contact,
  Meeting,
  OutreachData,
  Reply,
  ReplyClass,
  Signal,
  SignalStrength,
  SignalType,
  Touch,
} from "../shared/outreach.ts";

const SEED = 0x5eed_2026;
const AS_OF = Date.parse("2026-09-24T08:00:00.000Z");
const HISTORY_DAYS = 100;
const ACCOUNT_COUNT = 120;
const CONTACT_COUNT = 220;
const SIGNAL_COUNT = 300;
const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const OUT = path.join(import.meta.dirname, "..", "data", "outreach.json");

// mulberry32
let state = SEED >>> 0;
function random(): number {
  state = (state + 0x6d2b79f5) >>> 0;
  let t = state;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
}
const int = (min: number, max: number) => min + Math.floor(random() * (max - min + 1));
const pick = <T>(items: readonly T[]): T => items[Math.floor(random() * items.length)];
const chance = (p: number) => random() < p;
function weighted<T extends string>(weights: Record<T, number>): T {
  const entries = Object.entries(weights) as [T, number][];
  let roll = random() * entries.reduce((sum, [, w]) => sum + w, 0);
  for (const [value, weight] of entries) {
    roll -= weight;
    if (roll <= 0) return value;
  }
  return entries[entries.length - 1][0];
}
const pad = (n: number, width = 3) => String(n).padStart(width, "0");
const iso = (ms: number) => new Date(ms).toISOString();

/** Moves a timestamp into weekday working hours (08:00–18:00 UTC). */
function workingHours(ms: number): number {
  const date = new Date(ms);
  const hour = date.getUTCHours();
  if (hour < 8) date.setUTCHours(8 + int(0, 2), int(0, 59));
  if (hour >= 18) {
    date.setUTCDate(date.getUTCDate() + 1);
    date.setUTCHours(8 + int(0, 3), int(0, 59));
  }
  const weekday = date.getUTCDay();
  if (weekday === 6) date.setUTCDate(date.getUTCDate() + 2);
  if (weekday === 0) date.setUTCDate(date.getUTCDate() + 1);
  return date.getTime();
}

// ---------------------------------------------------------------------------
// Vocabulary
// ---------------------------------------------------------------------------

const NAME_HEADS = [
  "Arc", "Nova", "Lumen", "Vector", "Quanta", "Helix", "Tandem", "Cobalt", "Kestrel", "Brightwave",
  "Parallax", "Meridian", "Orbital", "Fathom", "Juniper", "Beacon", "Stratus", "Ledgerly", "Clearpath",
  "Pylon", "Mosaic", "Ferro", "Tessera", "Evergreen", "Sable", "Waypoint", "Crux", "Driftwood", "Halcyon",
  "Radiant", "Onyx", "Verity", "Glacier", "Summit", "Atlas", "Bramble", "Canopy", "Ember", "Foundry",
  "Granite", "Harbor", "Inkwell", "Jetstream", "Keel", "Lattice", "Monarch", "Northwind", "Oakline",
  "Prism", "Quill", "Relay", "Sparrow", "Tidal", "Umbra", "Vantage", "Willow", "Zephyr", "Anvil",
  "Basalt", "Cinder", "Dovetail", "Elm", "Flint", "Gable", "Heron", "Iris", "Jasper", "Kite", "Loom",
];
const NAME_TAILS = [
  "Labs", "AI", "HQ", "Cloud", "Systems", "Data", "Health", "Pay", "Logistics", "Security", "Analytics",
  "Works", "Robotics", "Bio", "Finance", "Commerce", "Networks", "Software", "Metrics", "Ops",
];
const INDUSTRIES = [
  "B2B SaaS", "Fintech", "Healthtech", "Logistics tech", "Cybersecurity", "Developer tools", "Martech",
  "HR tech", "Data infrastructure", "Insurtech", "Proptech", "E-commerce infrastructure",
];
const REGIONS: Record<string, readonly string[]> = {
  "North America": ["San Francisco", "New York", "Austin", "Boston", "Toronto", "Seattle", "Denver"],
  UK: ["London", "Manchester", "Edinburgh", "Bristol"],
  DACH: ["Berlin", "Munich", "Zurich", "Vienna", "Hamburg"],
  Nordics: ["Stockholm", "Copenhagen", "Oslo", "Helsinki"],
  "Western Europe": ["Amsterdam", "Paris", "Dublin", "Barcelona", "Lisbon", "Brussels"],
  APAC: ["Singapore", "Sydney", "Bangalore"],
};
const EU_REGIONS = new Set(["UK", "DACH", "Nordics", "Western Europe"]);

const FIRST_NAMES = [
  "Olivia", "Liam", "Priya", "Mateo", "Hannah", "Noah", "Aisha", "Lucas", "Mei", "Ethan", "Sofia", "Jonas",
  "Amara", "Daniel", "Chloe", "Rafael", "Ingrid", "Samuel", "Yuki", "Marcus", "Elena", "Tobias", "Grace",
  "Omar", "Freya", "Adrian", "Leila", "Henrik", "Nina", "Julian", "Zara", "Felix", "Camille", "Arjun",
  "Isabel", "Viktor", "Maya", "Diego", "Astrid", "Kofi", "Laura", "Benedikt", "Ruth", "Kenji", "Clara",
  "Tomás", "Sienna", "Oskar", "Fatima", "Theo",
];
const LAST_NAMES = [
  "Andersson", "Patel", "Okafor", "Müller", "Chen", "Rossi", "García", "Nakamura", "Johansson", "Dubois",
  "Kowalski", "O'Brien", "Nguyen", "Fischer", "Silva", "Haddad", "Larsen", "Moreau", "Schmidt", "Kim",
  "Brennan", "Ivanova", "Mensah", "Novak", "Walsh", "Bergström", "Costa", "Weber", "Taylor", "Sato",
  "Hughes", "Eriksen", "Reyes", "Lindqvist", "Adeyemi", "Van Dijk", "Murphy", "Horvat", "Clarke", "Yilmaz",
];

type Persona = "finance" | "revops" | "sales";
const TITLES: Record<Persona, readonly string[]> = {
  finance: ["CFO", "VP Finance", "Head of Finance", "Financial Controller", "Director of FP&A"],
  revops: [
    "VP Revenue Operations", "Head of RevOps", "Director of GTM Operations", "Sales Ops Manager",
    "Revenue Operations Lead",
  ],
  sales: ["VP Sales", "Head of Sales Development", "SDR Manager", "Chief Revenue Officer", "Director of Sales"],
};

const INVESTORS = [
  "Accel", "Index Ventures", "Point Nine", "Balderton", "Sequoia", "Lightspeed", "Northzone", "Creandum",
  "Atomico", "HV Capital", "Earlybird", "Bessemer", "Redpoint", "General Catalyst", "LocalGlobe",
];
const PREVIOUS_EMPLOYERS = ["Stripe", "Brex", "HubSpot", "Datadog", "Personio", "Revolut", "Klarna", "Snowflake", "Zendesk", "Adyen"];
const TOOL_SWAPS = [
  "Replaced Outreach with Salesloft",
  "Migrated CRM from Pipedrive to HubSpot",
  "Added Clay for account enrichment",
  "Rolled out Gong across the sales team",
  "Moved from Salesforce CPQ to DealHub",
  "Started a Snowflake + dbt rollout for revenue data",
  "Dropped ZoomInfo, trialing Apollo",
  "Adopted Chili Piper for inbound routing",
];
const G2_CATEGORIES = [
  "Sales Engagement (Outreach vs Apollo)",
  "Revenue Intelligence",
  "Lead-to-Account Matching",
  "Sales Intelligence (ZoomInfo alternatives)",
  "Pipeline forecasting tools",
  "Spend management vs FP&A suites",
];
const INTENT_PAGES = ["/pricing", "/integrations/salesforce", "/security", "/customers", "/docs/api", "/compare"];

// ---------------------------------------------------------------------------
// Campaigns and their 3-step sequences
// ---------------------------------------------------------------------------

const SENDER = {
  name: "Maya Lindqvist",
  title: "Account Executive",
  company: "Northstar",
  email: "maya@northstar.io",
};

const CAMPAIGNS: (Campaign & { persona: Persona })[] = [
  {
    id: "series-a-cfo",
    name: "Series A SaaS — CFO",
    persona: "finance",
    description: "Finance leaders at freshly funded SaaS companies building their first real planning stack.",
    sequence: [
      {
        step: 1,
        dayOffset: 0,
        subject: "Pipeline numbers at {{company}}",
        body:
          "Hi {{first}},\n\n{{hook}}. Moments like this are usually when the board starts asking for a pipeline number finance can actually defend.\n\nNorthstar ties CRM pipeline to your plan, so forecast, CAC payback and hiring capacity come from the same numbers. Teams like Tessera Pay cut their month-end forecast prep from 4 days to half a day.\n\nWorth a 20-minute look before your next board meeting?\n\nMaya",
      },
      {
        step: 2,
        dayOffset: 3,
        subject: "Re: Pipeline numbers at {{company}}",
        body:
          "Hi {{first}},\n\nQuick follow-up with something concrete: I put together what a pipeline-to-plan view could look like for a team of {{employees}} people. Happy to walk you through it — it takes 15 minutes and you keep the model either way.\n\nMaya",
      },
      {
        step: 3,
        dayOffset: 7,
        subject: "Close the loop?",
        body:
          "Hi {{first}},\n\nI'll assume the timing isn't right and stop here. If forecasting becomes a board topic this quarter, just reply \"later\" and I'll check back in a month.\n\nMaya",
      },
    ],
  },
  {
    id: "revops-eu",
    name: "RevOps leaders EU",
    persona: "revops",
    description: "Revenue operations owners in Europe whose GTM stack is in motion.",
    sequence: [
      {
        step: 1,
        dayOffset: 0,
        subject: "{{company}}'s GTM stack",
        body:
          "Hi {{first}},\n\n{{hook}}. Moments like this are usually when routing rules and field mappings quietly break.\n\nNorthstar sits on top of your CRM and watches lead-to-account matching, routing and SLA drift, and flags what broke before reps notice. EU-hosted, GDPR DPA ready.\n\nOpen to a short call to compare notes?\n\nMaya",
      },
      {
        step: 2,
        dayOffset: 3,
        subject: "Re: {{company}}'s GTM stack",
        body:
          "Hi {{first}},\n\nOne data point: after a CRM or engagement-tool switch, the median team we see mis-routes 11% of inbound leads for the first six weeks. We audit that for free — would a read-out for {{company}} be useful?\n\nMaya",
      },
      {
        step: 3,
        dayOffset: 7,
        subject: "Should I close your file?",
        body:
          "Hi {{first}},\n\nNot hearing back usually means bad timing, so I'll leave it here. If routing or data hygiene lands on your plate this quarter, I'm one reply away.\n\nMaya",
      },
    ],
  },
  {
    id: "sdr-hiring",
    name: "Hiring SDR teams",
    persona: "sales",
    description: "Sales leaders scaling outbound headcount who need new reps productive fast.",
    sequence: [
      {
        step: 1,
        dayOffset: 0,
        subject: "Ramping outbound at {{company}}",
        body:
          "Hi {{first}},\n\n{{hook}}. If outbound is part of the plan, the hard part is rarely hiring reps — it's getting them to book meetings before month three.\n\nNorthstar gives every rep a daily list of accounts showing real buying signals (funding, hiring, stack changes, pricing-page visits) with the first line already written. New reps at Parallax Data booked their first meeting in week one.\n\nWorth 20 minutes to see it on your territories?\n\nMaya",
      },
      {
        step: 2,
        dayOffset: 3,
        subject: "Re: Ramping outbound at {{company}}",
        body:
          "Hi {{first}},\n\nI pulled 25 accounts in your ICP that fired a buying signal this week — happy to send the list over, no strings attached. Want it?\n\nMaya",
      },
      {
        step: 3,
        dayOffset: 7,
        subject: "Last note from me",
        body:
          "Hi {{first}},\n\nLast one from me. If ramp time or pipeline per rep becomes a problem as the team grows, reply with \"ramp\" and I'll send over how others have handled it.\n\nMaya",
      },
    ],
  },
];

const CAMPAIGN_FOR_SIGNAL: Record<SignalType, (region: string) => (typeof CAMPAIGNS)[number]["id"]> = {
  funding_round: () => "series-a-cfo",
  new_executive: () => "series-a-cfo",
  hiring_surge: () => "sdr-hiring",
  tech_stack_change: (region) => (EU_REGIONS.has(region) ? "revops-eu" : "sdr-hiring"),
  website_intent: (region) => (EU_REGIONS.has(region) ? "revops-eu" : "sdr-hiring"),
  g2_research: (region) => (EU_REGIONS.has(region) ? "revops-eu" : "series-a-cfo"),
};

// ---------------------------------------------------------------------------
// Replies
// ---------------------------------------------------------------------------

type ReplyContext = { first: string; company: string; referral: string; day: string };
const REPLY_TEMPLATES: Record<ReplyClass, readonly ((c: ReplyContext) => string)[]> = {
  interested: [
    (c) => `Hi Maya,\n\nTiming is actually decent — we're rebuilding our planning process right now and the board asked for a cleaner pipeline view. Can you send a short overview and rough pricing for a team our size?\n\n${c.first}`,
    () => `Thanks for reaching out. This is on our radar for Q4. Could you share a couple of customer references in a similar stage? If it looks relevant I'll pull in our Head of Sales.`,
    (c) => `Hey Maya — interesting. We just switched tools and I'm already seeing routing issues, so the audit could be useful. What do you need from us to run it?\n\n${c.first}`,
    () => `Happy to take a look. Send over the account list you mentioned and a few times next week that work for you.`,
  ],
  meeting_booked: [
    (c) => `Sure, let's talk. ${c.day} at 2pm CET works — I've grabbed a slot from your calendar link. Please include our VP Sales on the invite.`,
    (c) => `Good timing. Booked ${c.day} 10:30 via your link. Come prepared with numbers on ramp time, that's what I care about.\n\n${c.first}`,
    () => `Yes — let's do 30 minutes. I picked the first slot on your page. Looking forward to it.`,
  ],
  referral: [
    (c) => `Hi Maya, I'm not the right person for this. ${c.referral} owns our revenue tooling — copying them here.`,
    (c) => `Thanks — this sits with ${c.referral} since the reorg. Looping them in, please take me off the thread.`,
  ],
  not_now: [
    () => `Appreciate the note. We're heads-down on the board deck until end of quarter — ping me in November?`,
    (c) => `Not a priority for ${c.company} right now, we just froze new tooling spend until January. Feel free to check back then.`,
    () => `We're mid-migration and I can't take on another vendor conversation. Try me again in 6–8 weeks.`,
  ],
  objection: [
    () => `We already use Clari for this and just renewed for two years. Not sure what you'd add on top.`,
    () => `Honestly we tried a signal-based tool last year and the data was mostly noise. What makes yours different?`,
    () => `Budget is locked for this year and anything new needs security review, which takes months. Probably not worth your time.`,
  ],
  unsubscribe: [
    () => `Please remove me from your list.`,
    () => `Not interested. Please don't email me again.`,
    () => `Unsubscribe.`,
  ],
  out_of_office: [
    (c) => `I'm out of office until ${c.day} with limited access to email. For anything urgent please contact finance@${c.company.toLowerCase().replace(/[^a-z]/g, "")}.com.`,
    (c) => `Thanks for your email. I'm on parental leave and will be back on ${c.day}. Your message will not be forwarded.`,
    (c) => `Auto-reply: travelling for our offsite, back ${c.day}. I'll reply when I'm back.`,
  ],
};

// ---------------------------------------------------------------------------
// Generation
// ---------------------------------------------------------------------------

const usedNames = new Set<string>();
const accounts: Account[] = [];
while (accounts.length < ACCOUNT_COUNT) {
  const name = `${pick(NAME_HEADS)} ${pick(NAME_TAILS)}`;
  if (usedNames.has(name)) continue;
  usedNames.add(name);
  const region = weighted({
    "North America": 34,
    UK: 14,
    DACH: 16,
    Nordics: 10,
    "Western Europe": 18,
    APAC: 8,
  });
  const slug = name.toLowerCase().replace(/[^a-z]/g, "");
  const employees = Math.round(Math.exp(3 + random() * 4.4) / 5) * 5 + 15;
  accounts.push({
    id: `acc_${pad(accounts.length + 1)}`,
    name,
    domain: `${slug}.${pick(["com", "com", "io", "ai", "co"])}`,
    industry: pick(INDUSTRIES),
    employees,
    region,
    hq: pick(REGIONS[region]),
  });
}

const contacts: (Contact & { persona: Persona })[] = [];
const usedEmails = new Set<string>();
function addContact(account: Account, persona: Persona) {
  for (;;) {
    const firstName = pick(FIRST_NAMES);
    const lastName = pick(LAST_NAMES);
    const local = `${firstName}.${lastName}`
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z.]/g, "");
    const email = `${local}@${account.domain}`;
    if (usedEmails.has(email)) continue;
    usedEmails.add(email);
    contacts.push({
      id: `ct_${pad(contacts.length + 1)}`,
      accountId: account.id,
      firstName,
      lastName,
      title: pick(TITLES[persona]),
      email,
      enrollment: null,
      persona,
    });
    return;
  }
}
// Every account has one person in a role some campaign targets; the rest are
// spread across accounts at random.
for (const account of accounts) {
  addContact(account, chance(0.45) ? "finance" : EU_REGIONS.has(account.region) ? "revops" : "sales");
}
while (contacts.length < CONTACT_COUNT) {
  const account = pick(accounts);
  addContact(account, pick<Persona>(["finance", "sales", "revops"]));
}

/** The signal as shown in the feed, plus the opening line our first email builds on. */
function describeSignal(type: SignalType, account: Account, contact: Contact): { description: string; hook: string } {
  const lower = (text: string) => text.charAt(0).toLowerCase() + text.slice(1);
  switch (type) {
    case "funding_round": {
      const round = account.employees < 60 ? pick(["Seed", "Series A"]) : pick(["Series A", "Series B", "Series B", "Series C"]);
      const amount = { Seed: int(3, 8), "Series A": int(9, 24), "Series B": int(25, 70), "Series C": int(60, 140) }[round]!;
      const description = `Raised $${amount}M ${round} led by ${pick(INVESTORS)}`;
      return { description, hook: `Saw that ${account.name} just ${lower(description)} — congrats` };
    }
    case "hiring_surge": {
      const roles = int(5, 14);
      return pick([
        { description: `Posted ${roles} SDR/BDR roles in the last 14 days`, hook: `Saw ${account.name} posted ${roles} SDR roles in the last two weeks` },
        { description: `Sales headcount up ${roles * 3}% in 90 days`, hook: `Noticed ${account.name}'s sales team grew by ${roles * 3}% this quarter` },
        {
          description: `Hiring a Head of Sales Development and ${roles} SDRs in ${account.hq}`,
          hook: `Saw ${account.name} is building out an SDR team in ${account.hq}`,
        },
      ]);
    }
    case "new_executive": {
      const previous = pick(PREVIOUS_EMPLOYERS);
      return {
        description: `${contact.firstName} ${contact.lastName} joined as ${contact.title} (ex-${previous})`,
        hook: `Congrats on joining ${account.name} as ${contact.title}`,
      };
    }
    case "tech_stack_change": {
      const description = pick(TOOL_SWAPS);
      return { description, hook: `Heard ${account.name} ${lower(description)}` };
    }
    case "website_intent": {
      const visitors = int(2, 5);
      return {
        description: `${int(visitors + 1, 11)} visits to ${pick(INTENT_PAGES)} from ${visitors} employees this week`,
        hook: `A few people at ${account.name} have been reading up on signal-based outbound`,
      };
    }
    case "g2_research":
      return {
        description: `Researching ${pick(G2_CATEGORIES)} on G2`,
        hook: `Looks like ${account.name} has been comparing tools in this category on G2`,
      };
  }
}

function render(template: string, account: Account, contact: Contact, hook: string): string {
  return template
    .replaceAll("{{first}}", contact.firstName)
    .replaceAll("{{company}}", account.name)
    .replaceAll("{{employees}}", String(account.employees))
    .replaceAll("{{hook}}", hook);
}

const accountById = new Map(accounts.map((a) => [a.id, a]));
const signals: Signal[] = [];
const touches: Touch[] = [];
const replies: Reply[] = [];
const meetings: Meeting[] = [];
const historyStart = AS_OF - HISTORY_DAYS * DAY;
const hooks = new Map<Signal, string>();

for (let i = 0; i < SIGNAL_COUNT; i++) {
  // Half uniform, half skewed toward recent days: steady growth over time.
  const age = chance(0.5) ? random() * HISTORY_DAYS : HISTORY_DAYS * (1 - Math.sqrt(random()));
  const detectedAt = AS_OF - age * DAY - int(0, 600) * 60_000;
  const type = weighted<SignalType>({
    funding_round: 16,
    hiring_surge: 20,
    new_executive: 12,
    tech_stack_change: 16,
    website_intent: 22,
    g2_research: 14,
  });
  // Only accounts with somebody the matching campaign targets.
  const candidates = accounts.flatMap((account) => {
    const campaign = CAMPAIGNS.find((c) => c.id === CAMPAIGN_FOR_SIGNAL[type](account.region))!;
    const fitting = contacts.filter((c) => c.accountId === account.id && c.persona === campaign.persona);
    return fitting.length > 0 ? [{ account, campaign, fitting }] : [];
  });
  const { account, campaign, fitting } = pick(candidates);
  const campaignId = campaign.id;
  const contact = pick(fitting);
  const strength = weighted<SignalStrength>(
    type === "funding_round" || type === "website_intent"
      ? { hot: 45, warm: 40, cold: 15 }
      : { hot: 22, warm: 48, cold: 30 },
  );
  const { description, hook } = describeSignal(type, account, contact);
  const signal: Signal = {
    id: "",
    accountId: account.id,
    contactId: contact.id,
    campaignId,
    type,
    description,
    strength,
    qualified: strength === "hot" || (strength === "warm" ? chance(0.8) : chance(0.2)),
    detectedAt: iso(detectedAt),
  };
  signals.push(signal);
  hooks.set(signal, hook);
}
signals.sort((a, b) => a.detectedAt.localeCompare(b.detectedAt));
signals.forEach((signal, index) => (signal.id = `sig_${pad(index + 1)}`));

let touchSeq = 0;
let replySeq = 0;
for (const signal of signals) {
  const contact = contacts.find((c) => c.id === signal.contactId)!;
  const account = accountById.get(signal.accountId)!;
  const campaign = CAMPAIGNS.find((c) => c.id === signal.campaignId)!;
  const detected = Date.parse(signal.detectedAt);
  if (!signal.qualified || contact.enrollment) continue;
  // The newest signals are the team's backlog; a few older ones slipped through.
  if (AS_OF - detected < 1.5 * DAY || chance(0.1)) continue;

  const enrolledAt = detected + int(2, 20) * HOUR;
  contact.enrollment = { campaignId: campaign.id, signalId: signal.id, enrolledAt: iso(enrolledAt) };
  const firstTouch = workingHours(enrolledAt + int(1, 18) * HOUR);
  const hook = hooks.get(signal)!;
  const replyP = signal.strength === "hot" ? 0.52 : 0.38;
  const replyAfterStep = chance(replyP) ? weighted({ 1: 50, 2: 32, 3: 18 }) : null;

  for (const template of campaign.sequence) {
    const sentAt = workingHours(firstTouch + template.dayOffset * DAY + int(-60, 60) * 60_000);
    if (sentAt > AS_OF) break;
    const opened = chance(template.step === 1 ? 0.64 : 0.52) || String(template.step) === replyAfterStep;
    const openedAt = opened ? Math.min(sentAt + int(4, 60 * 20) * 60_000, AS_OF) : null;
    const clickedAt = openedAt && chance(0.16) ? Math.min(openedAt + int(1, 30) * 60_000, AS_OF) : null;
    const touch: Touch = {
      id: `tch_${pad(++touchSeq, 4)}`,
      contactId: contact.id,
      campaignId: campaign.id,
      step: template.step,
      subject: render(template.subject, account, contact, hook),
      body: render(template.body, account, contact, hook),
      sentAt: iso(sentAt),
      openedAt: openedAt === null ? null : iso(openedAt),
      clickedAt: clickedAt === null ? null : iso(clickedAt),
    };
    touches.push(touch);

    if (String(template.step) !== replyAfterStep) continue;
    const receivedAt = workingHours((openedAt ?? sentAt) + int(10, 60 * 30) * 60_000);
    if (receivedAt > AS_OF) break;
    const classification = weighted<ReplyClass>({
      interested: 21,
      meeting_booked: 14,
      referral: 8,
      not_now: 17,
      objection: 13,
      out_of_office: template.step === 1 ? 20 : 8,
      unsubscribe: 8,
    });
    const colleague = contacts.find((c) => c.accountId === account.id && c.id !== contact.id);
    const context: ReplyContext = {
      first: contact.firstName,
      company: account.name,
      referral: colleague ? `${colleague.firstName} ${colleague.lastName}` : "our Head of RevOps",
      day: new Date(receivedAt + int(2, 9) * DAY).toLocaleDateString("en-US", {
        weekday: "long",
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      }),
    };
    const reply: Reply = {
      id: `rpl_${pad(++replySeq)}`,
      contactId: contact.id,
      campaignId: campaign.id,
      touchId: touch.id,
      receivedAt: iso(receivedAt),
      body: pick(REPLY_TEMPLATES[classification])(context),
      classification,
      handled: false,
      handledAt: null,
    };
    if (AS_OF - receivedAt > 3 * DAY && chance(0.75)) {
      reply.handled = true;
      reply.handledAt = iso(Math.min(receivedAt + int(1, 30) * HOUR, AS_OF));
    }
    replies.push(reply);

    const booksMeeting = classification === "meeting_booked" || (classification === "interested" && chance(0.45));
    const bookedAt = classification === "meeting_booked" ? receivedAt + int(5, 50) * 60_000 : workingHours(receivedAt + int(20, 70) * HOUR);
    if (booksMeeting && bookedAt <= AS_OF) {
      const value = Math.min(Math.max(account.employees * int(90, 160), 12_000), 180_000);
      meetings.push({
        id: `mtg_${pad(meetings.length + 1)}`,
        contactId: contact.id,
        accountId: account.id,
        campaignId: campaign.id,
        replyId: reply.id,
        bookedAt: iso(bookedAt),
        scheduledFor: iso(workingHours(bookedAt + int(2, 8) * DAY)),
        pipelineValue: Math.round(value / 500) * 500,
      });
    }
    break;
  }
}

const data: OutreachData = {
  version: 1,
  asOf: iso(AS_OF),
  historyStart: iso(historyStart),
  sender: SENDER,
  campaigns: CAMPAIGNS.map((campaign) => ({
    id: campaign.id,
    name: campaign.name,
    persona: campaign.persona,
    description: campaign.description,
    sequence: campaign.sequence,
  })),
  accounts,
  contacts: contacts.map(({ persona: _persona, ...contact }) => contact),
  signals,
  touches,
  replies,
  meetings,
};

await fs.mkdir(path.dirname(OUT), { recursive: true });
await fs.writeFile(OUT, `${JSON.stringify(data, null, 2)}\n`, "utf-8");
const enrolled = contacts.filter((c) => c.enrollment).length;
console.log(
  `Wrote ${path.relative(process.cwd(), OUT)}: ${accounts.length} accounts, ${contacts.length} contacts ` +
    `(${enrolled} enrolled), ${signals.length} signals, ${touches.length} touches, ` +
    `${replies.length} replies, ${meetings.length} meetings`,
);
