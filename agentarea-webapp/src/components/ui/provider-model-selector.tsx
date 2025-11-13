"use client";

import * as React from "react";
import { Bot, Check, ChevronDown, Plus, Search } from "lucide-react";
import type { components } from "@/api/schema";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { getProviderIconUrl } from "@/lib/provider-icons";
import { cn } from "@/lib/utils";

type LLMModelInstance = components["schemas"]["ModelInstanceResponse"];

export interface ProviderModelSelectorProps {
  modelInstances: LLMModelInstance[];
  value?: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  emptyMessage?: string | React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onAddProvider?: () => void;
}

// Группируем модели по конфигурациям провайдера (config_name)
const groupModelsByConfig = (instances: LLMModelInstance[]) => {
  const grouped = instances.reduce(
    (acc, instance) => {
      const configName = instance.config_name || "Default Configuration";
      if (!acc[configName]) {
        acc[configName] = [];
      }
      acc[configName].push(instance);
      return acc;
    },
    {} as Record<string, LLMModelInstance[]>
  );

  return Object.entries(grouped).map(([configName, instances]) => {
    const providerName = instances[0]?.provider_name || "Unknown Provider";
    return {
      configName,
      instances,
      providerName,
      icon: getProviderIconUrl(providerName),
    };
  });
};

export function ProviderModelSelector({
  modelInstances,
  value,
  onValueChange,
  placeholder = "Select a model",
  disabled = false,
  className,
  emptyMessage = "No models found.",
  open: controlledOpen,
  onOpenChange: setControlledOpen,
  onAddProvider,
}: ProviderModelSelectorProps) {
  const [popoverWidth, setPopoverWidth] = React.useState<string>("auto");
  const [popoverOpen, setPopoverOpen] = React.useState(false);
  const [selectedProvider, setSelectedProvider] = React.useState<string | null>(
    null
  );
  const [searchQuery, setSearchQuery] = React.useState("");
  const triggerRef = React.useRef<HTMLButtonElement>(null);

  const providers = groupModelsByConfig(modelInstances);

  // Находим выбранную модель
  const selectedModel = React.useMemo(() => {
    if (!value || modelInstances.length === 0) return null;
    return modelInstances.find((instance) => instance.id === value);
  }, [value, modelInstances]);

  // Находим конфигурацию выбранной модели
  const selectedProviderName = React.useMemo(() => {
    if (!selectedModel) return null;
    return selectedModel.config_name ?? "Default Configuration";
  }, [selectedModel]);

  // Use controlled state if provided, otherwise use internal state
  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : popoverOpen;

  const handlePopoverOpenChange = (open: boolean) => {
    if (isControlled) {
      setControlledOpen?.(open);
    } else {
      setPopoverOpen(open);
    }

    if (open && triggerRef.current) {
      const width = triggerRef.current.offsetWidth;
      setPopoverWidth(`${Math.max(width, 400)}px`);

      // Если модель не выбрана, выбираем первую конфигурацию
      if (!selectedModel && providers.length > 0) {
        setSelectedProvider(providers[0].configName);
      } else if (selectedModel && selectedProviderName) {
        // Если модель выбрана, выбираем соответствующую конфигурацию
        setSelectedProvider(selectedProviderName);
      }
    } else if (!open) {
      // При закрытии сбрасываем поиск, но оставляем выбранный провайдер
      setSearchQuery("");
    }
  };

  const handleModelSelect = (modelId: string) => {
    onValueChange(modelId);
    handlePopoverOpenChange(false);
  };

  const handleProviderSelect = (providerName: string) => {
    setSelectedProvider(providerName);
  };

  // Фильтруем конфигурации и модели по общему поиску
  const filteredProviders = React.useMemo(() => {
    if (!searchQuery) return providers;

    return providers.filter(
      (provider) =>
        provider.configName
          .toLowerCase()
          .includes(searchQuery.toLowerCase()) ||
        provider.providerName
          .toLowerCase()
          .includes(searchQuery.toLowerCase()) ||
        provider.instances.some(
          (instance) =>
            instance.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            (instance.config_name &&
              instance.config_name
                .toLowerCase()
                .includes(searchQuery.toLowerCase()))
        )
    );
  }, [providers, searchQuery]);

  // Фильтруем модели по выбранной конфигурации и поиску
  const filteredModels = React.useMemo(() => {
    if (!selectedProvider) return [];

    const provider = providers.find((p) => p.configName === selectedProvider);
    if (!provider) return [];

    if (!searchQuery) return provider.instances;

    return provider.instances.filter(
      (instance) =>
        instance.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (instance.config_name &&
          instance.config_name
            .toLowerCase()
            .includes(searchQuery.toLowerCase()))
    );
  }, [selectedProvider, providers, searchQuery]);

  const renderProviderIcon = (
    providerName: string,
    iconUrl?: string | null
  ) => {
    if (iconUrl) {
      return (
        <img
          src={iconUrl}
          alt={providerName}
          className="h-4 w-4 rounded dark:invert"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      );
    }

    return <Bot className="h-4 w-4 text-muted-foreground" />;
  };

  const renderModelIcon = (providerName: string) => {
    const iconUrl = getProviderIconUrl(providerName);
    return renderProviderIcon(providerName, iconUrl);
  };

  const renderDefaultTrigger = () => {
    if (selectedModel) {
      return (
        <div className="flex items-center gap-2">
          <div className="flex h-4 w-4 flex-shrink-0 items-center justify-center">
            {renderModelIcon(selectedModel.provider_name || "")}
          </div>
          <div className="flex flex-col items-start">
            <span className="text-xs">{selectedModel.name}</span>
            <span className="text-[10px] leading-none text-muted-foreground font-normal">
              {selectedModel.config_name || selectedModel.provider_name}
            </span>
          </div>
        </div>
      );
    }
    return (
      <div className="flex items-center gap-2">
        <span className="font-normal text-inputSize text-muted-foreground">{placeholder}</span>
      </div>
    );
  };

  return (
    <Popover open={isOpen} onOpenChange={handlePopoverOpenChange}>
      <PopoverTrigger asChild>
        <Button
          ref={triggerRef}
          variant="outline"
          role="combobox"
          className={cn(
            "w-full justify-between rounded-md px-3 text-foreground shadow-none hover:bg-background hover:text-foreground focus:border-primary focus-visible:border-primary focus-visible:ring-0 dark:bg-zinc-900 dark:focus:border-accent-foreground dark:focus-visible:border-accent-foreground",
            className
          )}
          disabled={disabled}
        >
          {renderDefaultTrigger()}
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="p-0" style={{ width: popoverWidth }}>
        <div
          className={cn(
            "flex w-full flex-col",
            modelInstances.length === 0 ? "h-[200px]" : "h-[270px]"
          )}
        >
          {modelInstances.length === 0 ? (
            // Показываем emptyMessage на всю выпадашку если нет моделей
            <div className="flex flex-1 items-center justify-center p-6">
              {emptyMessage}
            </div>
          ) : (
            <>
              {/* Общий поиск */}
              <div className="border-b border-border">
                <div className="relative w-full">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 transform text-muted-foreground" />
                  <Input
                    placeholder="Search configurations and models"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full border-none pl-9"
                  />
                </div>
              </div>

              <div className="flex h-full flex-1 overflow-hidden">
                {/* Левая панель - Конфигурации */}
                <div className="flex w-[40%] flex-col border-r border-border bg-muted/20">
                  <div className="flex h-8 items-center justify-between border-b border-border px-2 py-1">
                    <h3 className="text-xs font-medium">Configurations</h3>
                    {onAddProvider && (
                      <Button
                        variant="secondary"
                        size="icon"
                        onClick={onAddProvider}
                        className="h-5 w-5"
                      >
                        <Plus className="h-3 w-3" />
                      </Button>
                    )}
                  </div>
                  <div className="flex-1 overflow-y-auto p-1">
                    {filteredProviders.map((provider) => (
                      <button
                        key={provider.configName}
                        onClick={() =>
                          handleProviderSelect(provider.configName)
                        }
                        className={cn(
                          "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left transition-colors",
                          selectedProvider === provider.configName &&
                            "bg-accent/20"
                        )}
                      >
                        <div className="flex h-4 w-4 flex-shrink-0 items-center justify-center md:h-5 md:w-5">
                          {renderProviderIcon(
                            provider.providerName,
                            provider.icon
                          )}
                        </div>
                        <span className="truncate text-xs font-medium">
                          {provider.configName}
                          <div className="text-[10px] leading-none text-muted-foreground font-normal">
                            {provider.providerName}
                          </div>
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Правая панель - Модели */}
                <div className="flex h-full w-[60%] flex-col overflow-hidden">
                  <div className="h-8 flex-shrink-0 border-b border-border px-2 py-2">
                    <h3 className="text-xs font-medium">Models</h3>
                  </div>
                  <div className="h-fullflex-1 min-h-0 overflow-hidden">
                    {!selectedProvider ? (
                      <div className="flex h-full items-center justify-center text-muted-foreground">
                        <span className="text-sm">
                          Select a configuration to view models
                        </span>
                      </div>
                    ) : (
                      <Command className="flex h-full flex-col">
                        <CommandList className="flex-1 overflow-y-auto">
                          <CommandEmpty>No models found</CommandEmpty>
                          <CommandGroup>
                            {filteredModels.map((model) => (
                              <CommandItem
                                key={model.id}
                                value={`${model.name} ${model.config_name || model.provider_name}`}
                                onSelect={() => handleModelSelect(model.id)}
                                className="relative overflow-hidden"
                              >
                                <div className="flex w-full items-center gap-3 overflow-hidden">
                                  <div className="flex min-w-0 flex-1 flex-col items-start overflow-hidden">
                                    <span className="w-full truncate text-xs font-medium">
                                      {model.name}
                                    </span>
                                  </div>
                                </div>
                                <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
                                  <Check
                                    className={cn(
                                      "h-4 w-4 text-accent dark:text-accent-foreground",
                                      value === model.id
                                        ? "opacity-100"
                                        : "opacity-0"
                                    )}
                                  />
                                </span>
                              </CommandItem>
                            ))}
                          </CommandGroup>
                        </CommandList>
                      </Command>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
