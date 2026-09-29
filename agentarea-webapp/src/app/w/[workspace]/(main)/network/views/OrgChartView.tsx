"use client";

import NetworkMapView, { type NetworkMapProps } from "./NetworkMapView";

export default function OrgChartView(props: Omit<NetworkMapProps, "mode">) {
  return <NetworkMapView {...props} mode="organization" />;
}
