export type LLMModel = {
    id: number;
    name: string;
    image: string;
    description: string;
    tags: string[];
    category: string;
}

export const list: LLMModel[] = [
    {
        id: 1,
        name: "ChatGPT",
        image: "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ef/ChatGPT-Logo.svg/1200px-ChatGPT-Logo.svg.png",
        description: "ChatGPT can generate human-like conversational responses and enables users to refine and steer a conversation towards a desired length, format, style, level of detail, and language.",
        tags: ["chat", "ai", "chatbot"],
        category: "chat"
    },
];