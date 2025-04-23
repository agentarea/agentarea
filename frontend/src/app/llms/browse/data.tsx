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
    {
        id: 2,
        name: "Gmail",
        description: "Connect to Gmail to send and manage emails.",
        image: "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Gmail_icon_%282020%29.svg/1280px-Gmail_icon_%282020%29.svg.png",
        tags: ["email", "communication"],
        category: "email"
    },
    {
        id: 3,
        name: "Stripe",
        description: "Stripe is a payment processor that allows you to accept payments online.",
        image: "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQVayvA1fb26-LrH9la3fxNJj4RGWMz6YcjIT9HdZMK13zv3TkeCcH3j-9oUm0rlnLaLhM&usqp=CAU",
        tags: ["payment", "ecommerce"],
        category: "payment"
    },
    {
        id: 4,
        name: "Mailchimp",
        description: "Mailchimp is an email marketing and automation platform providing campaign templates, audience segmentation, and performance analytics to drive engagement and conversions",
        image: "https://www.drupal.org/files/project-images/MC_Logo_0.jpg",
        tags: ["marketing", "social media", "email"],
        category: "email"
    },
    {
        id: 5,
        name: "Notion",
        description: "Notion centralizes notes, docs, wikis, and tasks in a unified workspace, letting teams build custom workflows for collaboration and knowledge management",
        image: "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Notion-logo.svg/1200px-Notion-logo.svg.png",
        tags: ["task management", "documents"],
        category: "task management"
    },
    {
        id: 6,
        name: "Hubspot",
        description: "HubSpot is an inbound marketing, sales, and customer service platform integrating CRM, email automation, and analytics to facilitate lead nurturing and seamless customer experiences",
        image: "https://cdn.worldvectorlogo.com/logos/hubspot-1.svg",
        tags: ["crm", "sales", "marketing"],
        category: "crm"
    },
    {
        id: 7,
        name: "Asana",
        description: "Tool to help teams organize, track, and manage their work.",
        image: "https://d1mzm9ptampqbl.cloudfront.net/product-logos/asana.png",
        tags: ["productivity", "management"],
        category: "task management"
    },
    {
        id: 8,
        name: "Jira",
        description: "A tool for bug tracking, issue tracking, and agile project management.",
        image: "https://cdn.worldvectorlogo.com/logos/jira-1.svg",
        tags: ["traking", "productivity", "management"],
        category: "task management"
    },
    {
        id: 9,
        name: "Dropbox",
        description: "Dropbox is a file hosting service that offers cloud storage, file synchronization, personal cloud, and client software.",
        image: "https://cdn.prod.website-files.com/66c503d081b2f012369fc5d2/674000d6c0a42d41f8c331be_dropbox-2-logo-png-transparent.png",
        tags: ["documents","file management"],
        category: "file management"
    },
];