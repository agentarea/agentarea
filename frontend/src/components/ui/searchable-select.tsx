"use client"

import * as React from "react"

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Button } from "@/components/ui/button"
import { ChevronDown, Check, Bot } from "lucide-react"
import { cn } from "@/lib/utils"

export interface SelectOption {
  id: string | number
  label: string
  description?: string
  icon?: string
}

export interface SimpleSelectOption {
  id: string | number
  label: string
}

interface SearchableSelectProps {
  options: (SelectOption | SimpleSelectOption)[]
  value?: string | number
  onValueChange: (value: string | number) => void
  placeholder?: string
  disabled?: boolean
  className?: string
  emptyMessage?: string | React.ReactNode
  defaultIcon?: React.ReactNode
  renderOption?: (option: SelectOption | SimpleSelectOption) => React.ReactNode
  renderTrigger?: (selectedOption: SelectOption | SimpleSelectOption | undefined) => React.ReactNode
}

export function SearchableSelect({
  options,
  value,
  onValueChange,
  placeholder = "Search...",
  disabled = false,
  className,
  emptyMessage = "No items found.",
  defaultIcon,
  renderOption,
  renderTrigger
}: SearchableSelectProps) {
  const [popoverWidth, setPopoverWidth] = React.useState<string>('auto')
  const [popoverOpen, setPopoverOpen] = React.useState(false)
  const triggerRef = React.useRef<HTMLButtonElement>(null)

  const selectedOption = options.find(option => option.id === value)

  const handlePopoverOpenChange = (open: boolean) => {
    setPopoverOpen(open)
    if (open && triggerRef.current) {
      const width = triggerRef.current.offsetWidth
      setPopoverWidth(`${width}px`)
    }
  }

  const handleOptionChange = (optionId: string | number) => {
    onValueChange(optionId)
    setPopoverOpen(false)
  }

  const renderIcon = (option: SelectOption) => {
    if (option.icon) {
      return (
        <img
          src={option.icon}
          alt={option.label}
          className="w-5 h-5 rounded dark:invert"
          onError={(e) => {
            if (defaultIcon) {
              e.currentTarget.style.display = 'none'
            }
          }}
        />
      )
    }
    
    return defaultIcon || <Bot className="w-5 h-5 text-muted-foreground" />
  }

  const renderOptionContent = (option: SelectOption | SimpleSelectOption) => (
    <div className="flex gap-3">
      {'icon' in option && renderIcon(option as SelectOption)}
      <div className="flex flex-col items-start">
        <span>{option.label}</span>
        {'description' in option && option.description && (
          <span className="note">{option.description}</span>
        )}
      </div>
    </div>
  )

  const renderDefaultTrigger = (selectedOption: SelectOption | SimpleSelectOption | undefined) => {
    if (selectedOption) {
      return renderOptionContent(selectedOption)
    }
    return (
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground font-normal">{placeholder}</span>
      </div>
    )
  }

  const renderDefaultOption = (option: SelectOption | SimpleSelectOption) => {
    const isSelected = option.id === value
    return (
      <>
        {renderOptionContent(option)}
        <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
          <Check 
            className={cn(
              "h-4 w-4 text-accent dark:text-accent-foreground",
              isSelected ? "opacity-100" : "opacity-0"
            )}
          />
        </span>
      </>
    )
  }

  return (
    <Popover open={popoverOpen} onOpenChange={handlePopoverOpenChange}>
      <PopoverTrigger asChild>
        <Button
          ref={triggerRef}
          variant="outline"
          role="combobox"
          className={cn(
            "px-3 w-full justify-between hover:bg-background shadow-none text-foreground hover:text-foreground focus:border-primary focus-visible:border-primary focus-visible:ring-0 dark:focus:border-accent-foreground dark:focus-visible:border-accent-foreground dark:bg-zinc-900", 
            className
          )}
          disabled={disabled}
        >
          {renderTrigger ? renderTrigger(selectedOption) : renderDefaultTrigger(selectedOption)}
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent 
        className="p-0"
        style={{ width: popoverWidth }}
      >
        <Command>
          <CommandInput placeholder={placeholder} />
          <CommandList>
            <CommandEmpty>{emptyMessage}</CommandEmpty>
            <CommandGroup>
              {options.map((option) => (
                <CommandItem
                  key={option.id}
                  value={option.label}
                  onSelect={() => {
                    handleOptionChange(option.id)
                  }}
                >
                  {renderOption ? renderOption(option) : renderDefaultOption(option)}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
} 