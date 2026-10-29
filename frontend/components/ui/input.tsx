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
        // Pass native input types through so date pickers, numeric keypads, and
        // other standard affordances keep working. TextInput's prop type only
        // declares text/email/password, but the value flows to a native <input>
        // at runtime, so any valid input type works.
        const inputType = (typeof type === "string" && type.length > 0 ? type : "text") as "text"

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
