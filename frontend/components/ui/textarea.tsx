import * as React from "react"
import { TextArea } from "@astryxdesign/core/TextArea"

import { cn } from "@/lib/utils"

export interface TextareaProps
    extends Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, "onChange"> {
    onChange?: React.ChangeEventHandler<HTMLTextAreaElement>
}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
    ({ className, disabled, required, value, name, autoFocus, placeholder, onChange, "aria-label": ariaLabel, ...props }, ref) => {
        const label = ariaLabel || placeholder || name || "Textarea"

        return (
            <TextArea
                ref={ref}
                label={label}
                isLabelHidden
                isDisabled={disabled}
                isRequired={required}
                hasAutoFocus={autoFocus}
                htmlName={name}
                placeholder={placeholder}
                value={value == null ? "" : String(value)}
                onChange={(_, event) => onChange?.(event)}
                className={cn(
                    "w-full",
                    className
                )}
                {...props}
            />
        )
    }
)
Textarea.displayName = "Textarea"

export { Textarea }
