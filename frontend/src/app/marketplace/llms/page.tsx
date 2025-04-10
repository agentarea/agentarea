import { redirect } from "next/navigation";

export default function LLMsPage() {
  // Main page redirects to the browse view
  redirect("/marketplace/llms/browse");
} 