import { Accordion as AccordionPrimitive } from "@base-ui/react/accordion";
import type { ComponentProps, ReactNode } from "react";

function classes(...values: Array<string | undefined>) {
  return values.filter(Boolean).join(" ");
}

type AccordionProps = Omit<
  ComponentProps<typeof AccordionPrimitive.Root>,
  "className"
> & {
  className?: string;
};

export function Accordion({ className, ...props }: AccordionProps) {
  return (
    <AccordionPrimitive.Root
      data-slot="accordion"
      className={classes("ui-accordion", className)}
      {...props}
    />
  );
}

type AccordionItemProps = Omit<
  ComponentProps<typeof AccordionPrimitive.Item>,
  "className"
> & {
  className?: string;
};

export function AccordionItem({ className, ...props }: AccordionItemProps) {
  return (
    <AccordionPrimitive.Item
      data-slot="accordion-item"
      className={classes("ui-accordion-item", className)}
      {...props}
    />
  );
}

type AccordionTriggerProps = Omit<
  ComponentProps<typeof AccordionPrimitive.Trigger>,
  "children" | "className"
> & {
  children: ReactNode;
  className?: string;
};

export function AccordionTrigger({
  children,
  className,
  ...props
}: AccordionTriggerProps) {
  return (
    <AccordionPrimitive.Header className="ui-accordion-header">
      <AccordionPrimitive.Trigger
        data-slot="accordion-trigger"
        className={classes("ui-accordion-trigger", className)}
        {...props}
      >
        {children}
        <svg
          className="ui-accordion-chevron"
          viewBox="0 0 16 16"
          aria-hidden="true"
        >
          <path d="m4 6 4 4 4-4" />
        </svg>
      </AccordionPrimitive.Trigger>
    </AccordionPrimitive.Header>
  );
}

type AccordionContentProps = Omit<
  ComponentProps<typeof AccordionPrimitive.Panel>,
  "children" | "className"
> & {
  children: ReactNode;
  className?: string;
};

export function AccordionContent({
  children,
  className,
  ...props
}: AccordionContentProps) {
  return (
    <AccordionPrimitive.Panel
      data-slot="accordion-content"
      className="ui-accordion-panel"
      {...props}
    >
      <div className={classes("ui-accordion-content", className)}>
        {children}
      </div>
    </AccordionPrimitive.Panel>
  );
}
