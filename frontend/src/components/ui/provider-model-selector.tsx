"use client"

import * as React from "react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Button } from "@/components/ui/button"
import { Command, CommandEmpty, CommandGroup, CommandItem, CommandList, CommandInput } from "@/components/ui/command"
import { ChevronDown, Check, Search, Bot, Plus } from "lucide-react"
import { cn } from "@/lib/utils"
import { Input } from "@/components/ui/input"
import { getProviderIconUrl } from "@/lib/provider-icons"
import type { components } from '@/api/schema';

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

// Группируем модели по провайдерам
const groupModelsByProvider = (instances: LLMModelInstance[]) => {
  const grouped = instances.reduce((acc, instance) => {
    const providerName = instance.provider_name || 'Unknown Provider';
    if (!acc[providerName]) {
      acc[providerName] = [];
    }
    acc[providerName].push(instance);
    return acc;
  }, {} as Record<string, LLMModelInstance[]>);

  return Object.entries(grouped).map(([providerName, instances]) => ({
    providerName,
    instances,
    icon: getProviderIconUrl(providerName)
  }));
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
  onAddProvider
}: ProviderModelSelectorProps) {
  const [popoverWidth, setPopoverWidth] = React.useState<string>('auto')
  const [popoverOpen, setPopoverOpen] = React.useState(false)
  const [selectedProvider, setSelectedProvider] = React.useState<string | null>(null)
  const [searchQuery, setSearchQuery] = React.useState("")
  const triggerRef = React.useRef<HTMLButtonElement>(null)

  const providers = groupModelsByProvider(modelInstances);

  // Находим выбранную модель
  const selectedModel = React.useMemo(() => {
    if (!value || modelInstances.length === 0) return null;
    return modelInstances.find(instance => instance.id === value);
  }, [value, modelInstances]);

  // Находим провайдера выбранной модели
  const selectedProviderName = React.useMemo(() => {
    if (!selectedModel) return null;
    return selectedModel.provider_name;
  }, [selectedModel]);

  // Use controlled state if provided, otherwise use internal state
  const isControlled = controlledOpen !== undefined
  const isOpen = isControlled ? controlledOpen : popoverOpen

  const handlePopoverOpenChange = (open: boolean) => {
    if (isControlled) {
      setControlledOpen?.(open)
    } else {
      setPopoverOpen(open)
    }
    
    if (open && triggerRef.current) {
      const width = triggerRef.current.offsetWidth
      setPopoverWidth(`${Math.max(width, 400)}px`)
      
      // Если модель не выбрана, выбираем первый провайдер
      if (!selectedModel && providers.length > 0) {
        setSelectedProvider(providers[0].providerName)
      } else if (selectedModel && selectedProviderName) {
        // Если модель выбрана, выбираем соответствующий провайдер
        setSelectedProvider(selectedProviderName)
      }
    } else if (!open) {
      // При закрытии сбрасываем поиск, но оставляем выбранный провайдер
      setSearchQuery("")
    }
  }

  const handleModelSelect = (modelId: string) => {
    onValueChange(modelId)
    handlePopoverOpenChange(false)
  }

  const handleProviderSelect = (providerName: string) => {
    setSelectedProvider(providerName)
  }

  // Фильтруем провайдеры и модели по общему поиску
  const filteredProviders = React.useMemo(() => {
    if (!searchQuery) return providers;
    
    return providers.filter(provider =>
      provider.providerName.toLowerCase().includes(searchQuery.toLowerCase()) ||
      provider.instances.some(instance =>
        instance.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (instance.config_name && instance.config_name.toLowerCase().includes(searchQuery.toLowerCase()))
      )
    );
  }, [providers, searchQuery]);

  // Фильтруем модели по выбранному провайдеру и поиску
  const filteredModels = React.useMemo(() => {
    if (!selectedProvider) return [];
    
    const provider = providers.find(p => p.providerName === selectedProvider);
    if (!provider) return [];

    if (!searchQuery) return provider.instances;

    return provider.instances.filter(instance =>
      instance.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (instance.config_name && instance.config_name.toLowerCase().includes(searchQuery.toLowerCase()))
    );
  }, [selectedProvider, providers, searchQuery]);

  const renderProviderIcon = (providerName: string, iconUrl?: string | null) => {
    if (iconUrl) {
      return (
        <img
          src={iconUrl}
          alt={providerName}
          className="w-4 h-4 rounded dark:invert"
          onError={(e) => {
            e.currentTarget.style.display = 'none'
          }}
        />
      )
    }
    
    return <Bot className="w-4 h-4 text-muted-foreground" />
  }

  const renderModelIcon = (providerName: string) => {
    const iconUrl = getProviderIconUrl(providerName);
    return renderProviderIcon(providerName, iconUrl);
  }

  const renderDefaultTrigger = () => {
    if (selectedModel) {
      return (
        <div className="flex gap-2 items-center">
          <div className="flex items-center justify-center w-4 h-4 flex-shrink-0">
            {renderModelIcon(selectedModel.provider_name || '')}
          </div>
          <div className="flex flex-col items-start">
            <span className="text-xs">{selectedModel.name}</span>
            <span className="text-xs text-muted-foreground">
              {selectedModel.config_name || selectedModel.provider_name}
            </span>
          </div>
        </div>
      )
    }
    return (
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground font-normal">{placeholder}</span>
      </div>
    )
  }

  return (
    <Popover open={isOpen} onOpenChange={handlePopoverOpenChange}>
      <PopoverTrigger asChild>
        <Button
          ref={triggerRef}
          variant="outline"
          role="combobox"
          className={cn(
            "rounded-md px-3 w-full justify-between hover:bg-background shadow-none text-foreground hover:text-foreground focus:border-primary focus-visible:border-primary focus-visible:ring-0 dark:focus:border-accent-foreground dark:focus-visible:border-accent-foreground dark:bg-zinc-900", 
            className
          )}
          disabled={disabled}
        >
          {renderDefaultTrigger()}
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent 
        className="p-0"
        style={{ width: popoverWidth }}
      >
        <div className={cn(
          "flex flex-col w-full max-w-[600px]",
          modelInstances.length === 0 ? "h-[200px]" : "h-[270px]"
        )}>
          {modelInstances.length === 0 ? (
            // Показываем emptyMessage на всю выпадашку если нет моделей
            <div className="flex-1 flex items-center justify-center p-6">
              {emptyMessage}
            </div>
          ) : (
            <>
              {/* Общий поиск */}
              <div className="border-b border-border">
                <div className="relative w-full">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Search provider and models"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9 border-none w-full"
                  />
                </div>
              </div>
              
              <div className="flex flex-1 h-full overflow-hidden">
            {/* Левая панель - Провайдеры */}
            <div className="w-1/3 border-r border-border bg-muted/20 min-w-[120px] flex flex-col">
              <div className="h-8 py-1 px-2 border-b border-border flex items-center justify-between">
                <h3 className="font-medium text-xs">Providers</h3>
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
                  key={provider.providerName}
                  onClick={() => handleProviderSelect(provider.providerName)}
                  className={cn(
                    "w-full flex items-center gap-2 px-2 py-1.5 text-left transition-colors rounded-sm",
                    selectedProvider === provider.providerName && "bg-accent/20"
                  )}
                >
                  <div className="flex items-center justify-center w-4 h-4 md:w-5 md:h-5 flex-shrink-0">
                    {renderProviderIcon(provider.providerName, provider.icon)}
                  </div>
                  <span className="text-sm font-medium truncate">{provider.providerName}</span>
                </button>
              ))}
              </div>
            </div>

            {/* Правая панель - Модели */}
            <div className="w-2/3 flex flex-col min-w-[280px] h-full overflow-hidden">
              <div className="h-8 py-2 px-2 border-b border-border flex-shrink-0">
                <h3 className="font-medium text-xs">Models</h3>
              </div>
              <div className="h-fullflex-1 overflow-hidden min-h-0">
                {!selectedProvider ? (
                  <div className="flex items-center justify-center h-full text-muted-foreground">
                    <span className="text-sm">Select a provider to view models</span>
                  </div>
                ) : (
                  <Command className="h-full flex flex-col">
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
                            <div className="flex items-center gap-3 w-full overflow-hidden">
                              <div className="flex flex-col items-start min-w-0 flex-1 overflow-hidden">
                                <span className="text-xs font-medium truncate w-full">{model.name}</span>
                                <span className="text-xs text-muted-foreground truncate w-full">
                                  {model.config_name || model.provider_name}
                                </span>
                              </div>
                            </div>
                            <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
                              <Check 
                                className={cn(
                                  "h-4 w-4 text-accent dark:text-accent-foreground",
                                  value === model.id ? "opacity-100" : "opacity-0"
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
  )
}
