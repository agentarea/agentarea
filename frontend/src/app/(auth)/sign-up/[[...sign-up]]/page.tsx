import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-600 via-purple-600 to-indigo-700 dark:from-gray-900 dark:via-gray-800 dark:to-slate-900">
      <SignUp 
        signInUrl="/sign-in"
        appearance={{
          // elements: {
          //   formButtonPrimary: 
          //     "bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-md transition duration-200",
          //   card: "bg-white/95 dark:bg-gray-800/95 shadow-2xl rounded-xl backdrop-blur-sm border border-white/20 dark:border-gray-700/20",
          //   headerTitle: "text-gray-900 dark:text-white",
          //   headerSubtitle: "text-gray-600 dark:text-gray-400",
          //   socialButtonsBlockButton: 
          //     "border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700",
          //   dividerLine: "bg-gray-300 dark:bg-gray-600",
          //   dividerText: "text-gray-500 dark:text-gray-400",
          //   formFieldInput: 
          //     "border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white",
          //   formFieldLabel: "text-gray-700 dark:text-gray-300",
          //   footerActionLink: "text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300",
          // },
        }}
      />
    </div>
  );
}
