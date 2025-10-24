// Генератор случайных имен для агентов
// Создает абстрактные и универсальные имена, не привязанные к конкретным целям

const adjectives = [
  "Swift",
  "Bright",
  "Clever",
  "Agile",
  "Dynamic",
  "Smart",
  "Quick",
  "Sharp",
  "Bright",
  "Wise",
  "Nimble",
  "Efficient",
  "Proactive",
  "Adaptive",
  "Responsive",
  "Intelligent",
  "Capable",
  "Skilled",
  "Talented",
  "Gifted",
  "Innovative",
  "Creative",
  "Resourceful",
  "Versatile",
  "Flexible",
  "Reliable",
  "Trustworthy",
  "Dependable",
  "Consistent",
  "Stable",
];

const nouns = [
  "Assistant",
  "Helper",
  "Partner",
  "Aide",
  "Support",
  "Guide",
  "Advisor",
  "Consultant",
  "Specialist",
  "Expert",
  "Operator",
  "Manager",
  "Coordinator",
  "Facilitator",
  "Mediator",
  "Navigator",
  "Pilot",
  "Steward",
  "Guardian",
  "Protector",
  "Companion",
  "Ally",
  "Collaborator",
  "Teammate",
  "Colleague",
  "Agent",
  "Representative",
  "Delegate",
  "Ambassador",
  "Emissary",
];

const prefixes = [
  "AI",
  "Smart",
  "Digital",
  "Virtual",
  "Cyber",
  "Auto",
  "Pro",
  "Super",
  "Ultra",
  "Hyper",
  "Neo",
  "Meta",
  "Quantum",
  "Nano",
  "Micro",
  "Eco",
  "Bio",
  "Neuro",
  "Synth",
  "Tech",
];

export function generateAgentName(): string {
  // Выбираем случайный префикс (30% вероятность)
  const usePrefix = Math.random() < 0.3;

  // Выбираем случайные слова
  const adjective = adjectives[Math.floor(Math.random() * adjectives.length)];
  const noun = nouns[Math.floor(Math.random() * nouns.length)];

  if (usePrefix) {
    const prefix = prefixes[Math.floor(Math.random() * prefixes.length)];
    return `${prefix} ${adjective} ${noun}`;
  } else {
    return `${adjective} ${noun}`;
  }
}

// Альтернативная функция для генерации более коротких имен
export function generateShortAgentName(): string {
  const shortAdjectives = [
    "Smart",
    "Quick",
    "Bright",
    "Wise",
    "Sharp",
    "Fast",
    "Good",
    "Best",
    "Top",
    "Prime",
  ];

  const shortNouns = [
    "Bot",
    "AI",
    "Agent",
    "Helper",
    "Aide",
    "Guide",
    "Buddy",
    "Pal",
    "Mate",
    "Friend",
  ];

  const adjective =
    shortAdjectives[Math.floor(Math.random() * shortAdjectives.length)];
  const noun = shortNouns[Math.floor(Math.random() * shortNouns.length)];

  return `${adjective} ${noun}`;
}
