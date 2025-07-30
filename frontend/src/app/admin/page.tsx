import Link from 'next/link';
import { Server, Brain, Key, BarChart3 } from 'lucide-react';
import { getTranslations } from 'next-intl/server';

export default async function AdminDashboard() {
  const t = await getTranslations("admin");
  
  const adminSections = [
    {
      title: t("sections.providers.title"),
      description: t("sections.providers.description"),
      href: '/admin/providers',
      icon: Server,
      color: 'bg-green-50 text-green-600 border-green-200 hover:bg-green-100'
    },
    {
      title: t("sections.providerConfigs.title"),
      description: t("sections.providerConfigs.description"),
      href: '/admin/provider-configs',
      icon: Key,
      color: 'bg-blue-50 text-blue-600 border-blue-200 hover:bg-blue-100'
    },
    {
      title: t("sections.modelSpecs.title"),
      description: t("sections.modelSpecs.description"),
      href: '/admin/model-specs',
      icon: Brain,
      color: 'bg-purple-50 text-purple-600 border-purple-200 hover:bg-purple-100'
    }
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">{t("title")}</h1>
        <p className="text-gray-600 mt-2">
          {t("overview")}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {adminSections.map((section) => {
          const IconComponent = section.icon;
          return (
            <Link
              key={section.href}
              href={section.href}
              className={`block p-6 rounded-lg border-2 transition-all duration-200 ${section.color}`}
            >
              <div className="flex items-center space-x-3 mb-3">
                <IconComponent className="h-8 w-8" />
                <h3 className="text-xl font-semibold">{section.title}</h3>
              </div>
              <p className="text-sm opacity-80">
                {section.description}
              </p>
            </Link>
          );
        })}
      </div>

      <div className="mt-12 p-6 bg-gray-50 rounded-lg border">
        <div className="flex items-center space-x-3 mb-3">
          <BarChart3 className="h-6 w-6 text-gray-600" />
          <h3 className="text-lg font-semibold text-gray-900">{t("quickStats.title")}</h3>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
          <div>
            <div className="text-2xl font-bold text-blue-600">54+</div>
            <div className="text-sm text-gray-600">{t("quickStats.aiProviders")}</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-green-600">Active</div>
            <div className="text-sm text-gray-600">{t("quickStats.systemStatus")}</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-purple-600">Ready</div>
            <div className="text-sm text-gray-600">{t("quickStats.forProduction")}</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-orange-600">24/7</div>
            <div className="text-sm text-gray-600">{t("quickStats.support")}</div>
          </div>
        </div>
      </div>
    </div>
  );
} 