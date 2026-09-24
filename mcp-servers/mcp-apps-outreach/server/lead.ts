import type { Contact, OutreachData, Signal } from "../shared/outreach.ts";
import type { LeadCard, LeadStep } from "../shared/schema.ts";
import { DAY, Index, shortDate, suggestedNextStep } from "./snapshot.ts";

const ACCOUNT_SIGNAL_LIMIT = 5;

const signalCard = (signal: Signal) => ({
  id: signal.id,
  type: signal.type,
  description: signal.description,
  strength: signal.strength,
  detectedAt: signal.detectedAt,
});

function nextStepWithoutReply(card: Omit<LeadCard, "suggestedNextStep">, contact: Contact): string {
  const { enrollment, targetCampaign, signal, account } = card;
  if (!enrollment) {
    if (!targetCampaign) return `No buying signal on ${contact.firstName} yet — keep them out of sequences until one fires.`;
    return signal
      ? `Add ${contact.firstName} to “${targetCampaign.name}” while “${signal.description}” is still fresh; step 1 goes out within a day.`
      : `Add ${contact.firstName} to “${targetCampaign.name}”; step 1 goes out within a day.`;
  }
  switch (enrollment.status) {
    case "scheduled":
      return `Step 1 is scheduled. Nothing to do until it goes out.`;
    case "in_sequence": {
      const opened = card.steps.some((s) => s.openedAt);
      const next = enrollment.nextTouchAt ? ` goes out ${shortDate(enrollment.nextTouchAt)}` : " is next";
      return `Step ${enrollment.step + 1}${next}.${opened ? ` ${contact.firstName} opened an earlier email — a short LinkedIn note before it lands could lift the reply odds.` : ""}`;
    }
    case "finished":
      return `The sequence ended without a reply. Try a different angle in a month, or reach another person at ${account.name}.`;
    default:
      return `Nothing scheduled for ${contact.firstName}.`;
  }
}

/** The lead card for one person. Throws for an unknown id. */
export function buildLeadCard(data: OutreachData, contactId: string): LeadCard {
  const index = new Index(data);
  const contact = index.contacts.get(contactId);
  if (!contact) {
    throw new Error(`No contact with id "${contactId}". Contact ids look like "ct_001"; open the outreach dashboard to find one.`);
  }
  const account = index.accounts.get(contact.accountId)!;
  const ownSignals = data.signals.filter((s) => s.contactId === contact.id);
  const signal = index.enrollmentSignal(contact) ?? ownSignals.at(-1);
  const touches = index.touchesOf(contact.id);
  const replies = data.replies
    .filter((r) => r.contactId === contact.id)
    .toSorted((a, b) => a.receivedAt.localeCompare(b.receivedAt));
  const latestReply = replies.at(-1);
  const meeting = index.meetings.get(contact.id);

  const enrollment = contact.enrollment
    ? {
        campaign: index.campaignRef(contact.enrollment.campaignId),
        enrolledAt: contact.enrollment.enrolledAt,
        ...index.sequenceState({ ...contact, enrollment: contact.enrollment }),
      }
    : null;
  const targetCampaign = enrollment ? null : signal ? index.campaignRef(signal.campaignId) : null;
  const sequence = index.campaigns.get(enrollment?.campaign.id ?? targetCampaign?.id ?? "")?.sequence ?? [];
  const stopped = enrollment !== null && ["replied", "meeting", "unsubscribed"].includes(enrollment.status);

  const steps: LeadStep[] = sequence.map((template, i) => {
    const touch = touches[i];
    if (touch) {
      const answered = replies.some((r) => r.touchId === touch.id && r.classification !== "out_of_office");
      return {
        step: template.step,
        subject: touch.subject,
        state: answered ? "replied" : touch.clickedAt ? "clicked" : touch.openedAt ? "opened" : "sent",
        sentAt: touch.sentAt,
        openedAt: touch.openedAt,
        clickedAt: touch.clickedAt,
        dueAt: null,
      };
    }
    const base = touches[0]?.sentAt ?? contact.enrollment?.enrolledAt;
    return {
      step: template.step,
      subject: template.subject.replaceAll("{{company}}", account.name),
      state: !enrollment ? "not_started" : stopped ? "skipped" : "scheduled",
      sentAt: null,
      openedAt: null,
      clickedAt: null,
      dueAt: enrollment && !stopped && base ? new Date(Date.parse(base) + template.dayOffset * DAY).toISOString() : null,
    };
  });

  const card: Omit<LeadCard, "suggestedNextStep"> = {
    asOf: data.asOf,
    generatedAt: new Date().toISOString(),
    contact: {
      id: contact.id,
      name: `${contact.firstName} ${contact.lastName}`,
      firstName: contact.firstName,
      title: contact.title,
      email: contact.email,
    },
    account: {
      name: account.name,
      domain: account.domain,
      industry: account.industry,
      employees: account.employees,
      region: account.region,
      hq: account.hq,
    },
    signal: signal ? signalCard(signal) : null,
    accountSignals: data.signals
      .filter((s) => s.accountId === account.id && s.id !== signal?.id)
      .toSorted((a, b) => b.detectedAt.localeCompare(a.detectedAt))
      .slice(0, ACCOUNT_SIGNAL_LIMIT)
      .map(signalCard),
    enrollment,
    targetCampaign,
    steps,
    thread: index.thread(contact),
    reply: latestReply
      ? {
          id: latestReply.id,
          classification: latestReply.classification,
          handled: latestReply.handled,
          receivedAt: latestReply.receivedAt,
        }
      : null,
    meeting: meeting ? { scheduledFor: meeting.scheduledFor, pipelineValue: meeting.pipelineValue } : null,
  };
  return {
    ...card,
    suggestedNextStep: latestReply
      ? suggestedNextStep(latestReply, contact, index.enrollmentSignal(contact), meeting)
      : nextStepWithoutReply(card, contact),
  };
}

export function summarizeLead(card: LeadCard): string {
  const status = card.enrollment
    ? `${card.enrollment.status.replace("_", " ")} in “${card.enrollment.campaign.name}” (step ${card.enrollment.step}/${card.enrollment.totalSteps})`
    : "not in a sequence";
  return [
    `${card.contact.name}, ${card.contact.title} at ${card.account.name} (${card.account.industry}, ${card.account.employees} people, ${card.account.region}) — ${status}.`,
    card.signal ? `Signal: ${card.signal.description} (${card.signal.strength}).` : "No buying signal on record.",
    card.reply ? `Latest reply: ${card.reply.classification.replace("_", " ")}${card.reply.handled ? "" : ", not handled yet"}.` : "",
    `Next step: ${card.suggestedNextStep}`,
  ]
    .filter(Boolean)
    .join(" ");
}
