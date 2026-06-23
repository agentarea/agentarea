import { useCallback } from "react"
import { useFormContext } from "react-hook-form"
import { useComponents, useOryFlow } from "../../../../context"
import { OryNodeButtonButtonProps } from "../../../../types"
import { UiNodeInput } from "../../../../util/utilFixSDKTypesHelper"

type SsoButtonProps = {
  node: UiNodeInput
}

export function extractProvider(
  context: object | undefined,
): string | undefined {
  if (
    context &&
    typeof context === "object" &&
    "provider" in context &&
    typeof context.provider === "string"
  ) {
    return context.provider
  }
  return undefined
}

export function SSOButtonRenderer({ node }: SsoButtonProps) {
  const { Node } = useComponents()
  const { pendingSocialNodeValue } = useOryFlow()
  const attributes = node.attributes
  const isPending = pendingSocialNodeValue === String(attributes.value)

  const {
    setValue,
    formState: { isSubmitting, isReady },
  } = useFormContext()

  const clickHandler = useCallback(() => {
    setValue("provider", attributes.value)
    setValue("method", node.group)
  }, [setValue, attributes.value, node.group])

  const buttonProps = {
    type: "submit",
    name: attributes.name,
    value: attributes.value,
    onClick: clickHandler,
    disabled: attributes.disabled || !isReady || isSubmitting || isPending,
  } satisfies OryNodeButtonButtonProps
  const provider = extractProvider(node.meta.label?.context) ?? ""

  return (
    <Node.SsoButton
      node={node}
      attributes={attributes}
      buttonProps={buttonProps}
      provider={provider}
      isSubmitting={isPending}
    />
  )
}
