"use client";

import NetworkMapView, { type NetworkMapProps } from "./NetworkMapView";

export default function AccessGraphView(props: Omit<NetworkMapProps, "mode">) {
  return <NetworkMapView {...props} mode="access" />;
}
