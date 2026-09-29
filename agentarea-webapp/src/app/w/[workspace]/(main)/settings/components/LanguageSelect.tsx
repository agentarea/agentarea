"use client";

import { useLocale } from "next-intl";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export default function LanguageSelect() {
  const locale = useLocale() as "en" | "ru";

  const onSelectChange = (value: string) => {
    const newLocale = value as "en" | "ru";
    document.cookie = `NEXT_LOCALE=${newLocale}; path=/; max-age=31536000; SameSite=Lax`;
    window.location.reload();
  };

  return (
    <Select value={locale} onValueChange={onSelectChange}>
      <SelectTrigger className="w-[140px]">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="en">English</SelectItem>
        <SelectItem value="ru">Русский</SelectItem>
      </SelectContent>
    </Select>
  );
}
