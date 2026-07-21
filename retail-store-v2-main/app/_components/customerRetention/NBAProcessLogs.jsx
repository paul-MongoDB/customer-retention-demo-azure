import Card from '@leafygreen-ui/card'
import { H3 } from '@leafygreen-ui/typography'
import React, { useState } from 'react'
import { useSelector,  } from 'react-redux'
import SectionHeader from './SectionHeader'
import Icon from '@leafygreen-ui/icon'
import IconButton from '@leafygreen-ui/icon-button'
import { getNextBestActionConfig, getBehaviorConfig } from '@/lib/helpers'
import useAutoScroll from '@/hooks/useAutoScroll'

const LogItem = ({ log }) => {
  const [isOpen, setIsOpen] = useState(false);
  
  const getBehaviorLabel = (type) => {
    return type?.replace(/-/g, " ").replace(/\b\w/g, c => c.toUpperCase()) || ""
  };

  const processTriggeredBySignal = (signalText) => {
    if (!signalText) return "";
    const underscoreIdx = signalText.indexOf('_');
    if (underscoreIdx < 0) return signalText;
    const severity = signalText.slice(0, underscoreIdx);
    const signalType = signalText.slice(underscoreIdx + 1);
    if (!severity || !signalType) return signalText;

    const capitalizedSeverity = severity.charAt(0).toUpperCase() + severity.slice(1).toLowerCase();
    const signalLabel = getBehaviorConfig(signalType)?.label || signalType;

    // Avoid stutter like "High High Intent" when severity matches the signal name
    if (signalLabel.toLowerCase().startsWith(capitalizedSeverity.toLowerCase())) {
      return signalLabel;
    }
    return `${capitalizedSeverity} ${signalLabel}`;
  };

  const triggeredBySignalProcessed = processTriggeredBySignal(log?.actionMetadata?.triggeredBySignal);

  // Extract timestamp from MongoDB ObjectId if no ts field exists
  const getTimestamp = () => {
    if (log?.ts) return new Date(log.ts);
    if (log?._id && typeof log._id === 'string' && log._id.length === 24) {
      return new Date(parseInt(log._id.substring(0, 8), 16) * 1000);
    }
    return null;
  };
  const tsDate = getTimestamp();
  const timeAgo = tsDate && !isNaN(tsDate) ? Math.floor((Date.now() - tsDate) / 60000) : null;

  return (
    <div 
      style={{
        backgroundColor: "white",
        border: "1px solid #e0e0e0",
        borderRadius: "12px",
        padding: "16px",
        marginBottom: "12px",
        boxShadow: "0 2px 8px rgba(0,0,0,0.08)"
      }}
    >
      <div className="d-flex justify-content-between align-items-start">
        <div className="d-flex align-items-start">
          <div 
            style={{
              backgroundColor: "#f5f5f5",
              borderRadius: "8px",
              padding: "8px",
              marginRight: "12px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center"
            }}
          >
            <Icon
              glyph={getNextBestActionConfig(log?.type).icon}
              size={20}
              style={{ color: "#666" }}
            />
          </div>
          <div style={{ flex: 1 }}>
            <h4 style={{ 
              margin: "0 0 4px 0", 
              fontSize: "16px", 
              fontWeight: 600,
              color: "#333"
            }}>
              {getNextBestActionConfig(log?.type)?.label || log?.type?.replace(/-/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
            </h4>
            <p style={{ 
              margin: "0 0 8px 0", 
              fontSize: "14px", 
              color: "#666"
            }}>
              Triggered by: {triggeredBySignalProcessed} signal
            </p>
            {log?.actionMetadata?.enrichedDecision && (
              <p style={{
                margin: "0 0 8px 0",
                fontSize: "13px",
                color: "#016BF8",
                fontWeight: 600
              }}>
                {log.actionMetadata.baselineDecision} → {log.actionMetadata.enrichedDecision}
                {log.actionMetadata.churnRiskTier ? ` · churn ${log.actionMetadata.churnRiskTier}` : ""}
                {log.actionMetadata.churnProbability != null
                  ? ` (${Math.round(log.actionMetadata.churnProbability * 100)}%)`
                  : ""}
              </p>
            )}
            <div style={{
              display: "inline-block",
              backgroundColor: log.redeemed ? "#4CAF50" : "#f44336",
              color: "white",
              padding: "4px 12px",
              borderRadius: "16px",
              fontSize: "12px",
              fontWeight: 500
            }}>
              {log.redeemed ? "Redeemed" : "Not redeemed"}
            </div>
          </div>
        </div>
        <div className="d-flex flex-column align-items-center">
          <span style={{ 
            fontSize: "13px", 
            color: "#666",
            marginRight: "8px"
          }}>
            {timeAgo != null
              ? timeAgo < 1 ? "Just now"
              : timeAgo < 60 ? `${timeAgo}m ago`
              : `${Math.floor(timeAgo / 60)}h ago`
              : ""}
          </span>
          <IconButton 
            onClick={() => setIsOpen(!isOpen)} 
            aria-label="Toggle Details"
            size="small"
            style={{ minWidth: "32px", minHeight: "32px", marginTop: "8px" }}
          >
            <Icon 
              glyph="CurlyBraces" 
              size="default"
              style={{ color: "#666" }}
            />
          </IconButton>
        </div>
      </div>
      {isOpen && (
        <pre style={{
          backgroundColor: "#f8f9fa",
          padding: "12px",
          borderRadius: "6px",
          fontSize: "12px",
          marginTop: "12px",
          overflow: "auto"
        }}>
          {JSON.stringify(log, null, 2)}
        </pre>
      )}
    </div>
  );
};

const NBAProcessLogs = () => {
  const { data: nextBestActions} = useSelector(state => state.CustomerRetention.nextBestActions);
  const { containerRef } = useAutoScroll(nextBestActions);

  return (
    <Card className="mt-2">
      <SectionHeader
        title="3. Next Best Action decisions"
        amount={nextBestActions?.length?.toString()}
        learnMoreElement={
          <p className="m-0">The Next Best Action generated by the agent</p>
        }
      />

      <div className="list-container longer" ref={containerRef}>
        {nextBestActions.map((log) => (
          <LogItem key={`log-${log?._id}`} log={log} />
        ))}
      </div>
    </Card>
  )
}

export default NBAProcessLogs