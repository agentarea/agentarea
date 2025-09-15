import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";

export default async function RootPage() {
  const { userId } = await auth();
  
  // If user is authenticated, redirect to workplace
  if (userId) {
    redirect("/workplace");
  }
  
  // If user is not authenticated, show welcome page
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-600 via-purple-600 to-indigo-700 dark:from-gray-900 dark:via-gray-800 dark:to-slate-900">
      <div className="text-center text-white">
        <h1 className="text-4xl font-bold mb-4">Добро пожаловать в AgentArea</h1>
        <p className="text-xl mb-8">Платформа для создания и управления AI агентами</p>
        <div className="space-x-4">
          <a 
            href="/sign-in" 
            className="bg-white text-blue-600 px-6 py-3 rounded-lg font-semibold hover:bg-gray-100 transition duration-200 inline-block"
          >
            Войти
          </a>
          <a 
            href="/sign-up" 
            className="border-2 border-white text-white px-6 py-3 rounded-lg font-semibold hover:bg-white hover:text-blue-600 transition duration-200 inline-block"
          >
            Регистрация
          </a>
        </div>
      </div>
    </div>
  );
}
