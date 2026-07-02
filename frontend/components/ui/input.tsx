import * as React from "react"
import { TextInput } from "@astryxdesign/core/TextInput"
import { cn } from "@/lib/utils"

export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "size"> {
    error?: boolean
    onChange?: React.ChangeEventHandler<HTMLInputElement>
    size?: "sm" | "md" | "lg"
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
    ({ className, type = "text", error, disabled, required, value, name, autoFocus, placeholder, onChange, "aria-label": ariaLabel, ...props }, ref) => {
        const label = ariaLabel || placeholder || name || "Input"
        const inputType: "text" | "email" | "password" =
            type === "email" ? "email" : type === "password" ? "password" : "text"

        return (
            <TextInput
                ref={ref}
                type={inputType}
                label={label}
                isLabelHidden
                isDisabled={disabled}
                isRequired={required}
                hasAutoFocus={autoFocus}
                htmlName={name}
                placeholder={placeholder}
                value={value == null ? "" : String(value)}
                onChange={(_, event) => onChange?.(event)}
                status={error ? { type: "error" } : undefined}
                className={cn(
                    "w-full",
                    className
                )}
                {...props}
            />
        )
    }
)
Input.displayName = "Input"

export { Input }
