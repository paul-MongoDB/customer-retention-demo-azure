import Card from "@leafygreen-ui/card";
import Badge from "@leafygreen-ui/badge";
import React from "react";
import SectionHeader from "./SectionHeader";
import { CardTitle } from "react-bootstrap";
import { useSelector } from "react-redux";

const RISK_TIER_CONFIG = {
  High: { variant: "red", label: "High Risk" },
  Medium: { variant: "yellow", label: "Medium Risk" },
  Low: { variant: "green", label: "Low Risk" },
};

const ChurnRiskPanel = () => {
  const churnRisk = useSelector((state) => state.CustomerRetention.churnRisk);

  const tierConfig = churnRisk
    ? RISK_TIER_CONFIG[churnRisk.churn_risk_tier] || RISK_TIER_CONFIG.Medium
    : null;

  return (
    <Card className="mt-2 ChurnRiskPanel">
      <SectionHeader
        title="Churn Risk Prediction"
        subtitle={null}
        amount={null}
        learnMoreElement={null}
        extraHTMLElement={
          <Badge variant="blue" style={{ fontSize: "11px" }}>
            Microsoft Fabric ML
          </Badge>
        }
      />

      {!churnRisk ? (
        <div className="p-3 text-center" style={{ color: "#889397" }}>
          <p className="m-0" style={{ fontSize: "13px" }}>
            Awaiting ML prediction from Microsoft Fabric...
          </p>
          <p className="m-0 mt-1" style={{ fontSize: "12px", color: "#aab4b8" }}>
            Run the scoring notebook in Fabric to see predictions here in real time.
          </p>
        </div>
      ) : (
        <div>
          <div className="item">
            <p className="m-0">Risk Tier</p>
            <CardTitle>
              <Badge variant={tierConfig.variant}>{tierConfig.label}</Badge>
            </CardTitle>
          </div>
          <div className="item">
            <p className="m-0">Churn Probability</p>
            <CardTitle>{(churnRisk.churn_probability * 100).toFixed(1)}%</CardTitle>
          </div>
          <div className="item">
            <p className="m-0">Top Risk Factor</p>
            <CardTitle style={{ fontSize: "14px" }}>
              {churnRisk.top_risk_factor
                ? churnRisk.top_risk_factor.replace(/_/g, " ")
                : "N/A"}
            </CardTitle>
          </div>
          <div className="item">
            <p className="m-0">Engagement Rate</p>
            <CardTitle>
              {churnRisk.engagement_rate != null
                ? `${(churnRisk.engagement_rate * 100).toFixed(1)}%`
                : "N/A"}
            </CardTitle>
          </div>
          <div className="item">
            <p className="m-0">Total Signals Analyzed</p>
            <CardTitle>{churnRisk.total_signals || 0}</CardTitle>
          </div>
        </div>
      )}
    </Card>
  );
};

export default ChurnRiskPanel;
