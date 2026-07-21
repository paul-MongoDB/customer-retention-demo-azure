#!/usr/bin/env python3
"""
One-time setup script to register NBA agents in Azure AI Foundry portal.

This provides portal visibility for all agents, the workflow, and MCP tools.
All agents are invoked at runtime via agent_reference (Foundry Responses API).
Foundry handles MCP tool execution server-side.

Usage:
    az login
    python setup_agents.py

Environment variables:
    AZURE_AI_PROJECT_ENDPOINT      - Foundry project endpoint (required)
    AZURE_AI_MODEL_DEPLOYMENT_NAME - Model deployment name (default: gpt-5.4-mini)
    MCP_SERVER_URL                 - MongoDB MCP Server URL (required)
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, WorkflowAgentDefinition, MCPTool
from azure.identity import DefaultAzureCredential

# Import shared instructions from the runtime module
from foundry_agents import (
    CONTEXT_ANALYZER_INSTRUCTIONS,
    RECOMMENDATION_WRITER_INSTRUCTIONS,
    SOCIAL_PROOF_AGENT_INSTRUCTIONS,
    SHIPPING_DISCOUNT_AGENT_INSTRUCTIONS,
    SHIPPING_DISCOUNT_AGENT_ENRICHED_INSTRUCTIONS,
    CART_RESCUE_AGENT_INSTRUCTIONS,
    CART_RESCUE_AGENT_ENRICHED_INSTRUCTIONS,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PROJECT_ENDPOINT = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
MODEL = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5.4-mini")
MCP_CONNECTION_NAME = os.environ.get("MCP_CONNECTION_NAME", "mongodb-mcp-server")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "")
# Public URL of the churn scoring service (the enriched agent calls this). Must
# be reachable by Foundry, so set it to the deployed scoring Container App FQDN.
SCORING_SERVICE_URL = os.environ.get("SCORING_SERVICE_URL", "")

if not PROJECT_ENDPOINT:
    print("ERROR: AZURE_AI_PROJECT_ENDPOINT is required")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Workflow YAML (SearchFrictionWorkflow is invoked at runtime via agent_reference)
# ---------------------------------------------------------------------------

SEARCH_FRICTION_WORKFLOW_YAML = """\
kind: workflow
trigger:
  kind: OnConversationStart
  id: search_friction_trigger
  actions:
    - kind: SetVariable
      id: capture_input
      variable: Local.LatestMessage
      value: "=UserMessage(System.LastMessageText)"

    - kind: CreateConversation
      id: create_context_conv
      conversationId: Local.ContextConversationId

    - kind: CreateConversation
      id: create_reco_conv
      conversationId: Local.RecoConversationId

    - kind: InvokeAzureAgent
      id: context_analyzer
      description: Analyzes search patterns and produces intent + discount JSON
      conversationId: "=Local.ContextConversationId"
      agent:
        name: ContextAnalyzer
      input:
        messages: "=Local.LatestMessage"
      output:
        messages: Local.LatestMessage

    - kind: InvokeAzureAgent
      id: recommendation_writer
      description: Uses vector search to find product and insert NBA
      conversationId: "=Local.RecoConversationId"
      agent:
        name: RecommendationWriter
      input:
        messages: "=Local.LatestMessage"
      output:
        messages: Local.LatestMessage

    - kind: SendMessage
      id: send_final_reply
      message: "{Last(Local.LatestMessage).Text}"
"""

# ---------------------------------------------------------------------------
# Agent + workflow definitions
# ---------------------------------------------------------------------------

AGENT_DEFS = {
    "ContextAnalyzer": CONTEXT_ANALYZER_INSTRUCTIONS,
    "RecommendationWriter": RECOMMENDATION_WRITER_INSTRUCTIONS,
    "SocialProofAgent": SOCIAL_PROOF_AGENT_INSTRUCTIONS,
    "ShippingDiscountAgent": SHIPPING_DISCOUNT_AGENT_INSTRUCTIONS,
    "ShippingDiscountAgentEnriched": SHIPPING_DISCOUNT_AGENT_ENRICHED_INSTRUCTIONS,
    "CartRescueAgent": CART_RESCUE_AGENT_INSTRUCTIONS,
    "CartRescueAgentEnriched": CART_RESCUE_AGENT_ENRICHED_INSTRUCTIONS,
}

# Enriched agents that additionally get the Fabric churn scoring OpenAPI tool.
SCORING_TOOL_AGENTS = {"ShippingDiscountAgentEnriched", "CartRescueAgentEnriched"}

WORKFLOW_DEFS = {
    "SearchFrictionWorkflow": SEARCH_FRICTION_WORKFLOW_YAML,
}

# OpenAPI 3.0 spec describing the churn scoring service's POST /score. Registered
# as a Foundry OpenAPI tool on the enriched exit-risk agent so it can call the
# model in the moment. The server URL must be reachable by Foundry.
SCORING_OPENAPI_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Leafy Churn Scoring", "version": "1.0.0"},
    "servers": [{"url": SCORING_SERVICE_URL}],
    "paths": {
        "/score": {
            "post": {
                "operationId": "score_churn",
                "summary": "Score a customer's churn risk in real time using the Fabric-trained model.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "uid": {"type": "string", "description": "The customer's user id."}
                                },
                                "required": ["uid"],
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Churn score for the customer.",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }
                },
            }
        }
    },
}


def _build_scoring_tool():
    """Build the OpenAPI tool that lets the enriched agent call POST /score.

    Returns the tool object, or None if it cannot be built (missing URL, or the
    installed azure-ai-projects does not expose OpenApiTool). It is guarded so a
    failure here never breaks registration of the other agents. If your SDK
    version names these classes differently, adjust this one function; the
    documented fallback is to wrap the scorer as a second MCP tool.
    """
    if not SCORING_SERVICE_URL:
        print("  [warn] SCORING_SERVICE_URL not set; enriched agent will lack the scoring tool.")
        return None
    try:
        from azure.ai.projects.models import (
            OpenApiTool,
            OpenApiFunctionDefinition,
            OpenApiAnonymousAuthDetails,
        )
    except ImportError as e:
        print(f"  [warn] OpenApiTool unavailable in azure-ai-projects ({e}); enriched agent "
              "registered WITHOUT the scoring tool. See README for the MCP fallback.")
        return None
    try:
        # azure-ai-projects 2.2.x: OpenApiTool is a wrapper; name/description/spec/auth
        # live on a nested OpenApiFunctionDefinition (not direct kwargs on OpenApiTool).
        return OpenApiTool(
            openapi=OpenApiFunctionDefinition(
                name="score_churn",
                description=(
                    "Score a customer's churn risk in real time using the Fabric-trained model. "
                    "Input is the customer's uid; returns churn_risk_tier, churn_probability, "
                    "and top_risk_factor."
                ),
                spec=SCORING_OPENAPI_SPEC,
                auth=OpenApiAnonymousAuthDetails(),
            )
        )
    except Exception as e:  # noqa: BLE001 -- surface any constructor mismatch, keep setup working
        print(f"  [warn] could not build the OpenAPI scoring tool ({e}); enriched agent "
              "registered WITHOUT it. Verify the OpenApiTool API for your SDK version.")
        return None


def main():
    print(f"Foundry endpoint:  {PROJECT_ENDPOINT}")
    print(f"Model:             {MODEL}")
    print(f"MCP server URL:    {MCP_SERVER_URL}")
    print()

    credential = DefaultAzureCredential()
    client = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=credential,
        allow_preview=True,
    )

    mcp_tool = MCPTool(
        server_label="mongodb",
        server_url=MCP_SERVER_URL,
        require_approval="never",
    )

    # Delete existing agents so we can recreate with updated instructions
    all_agent_names = set(AGENT_DEFS.keys()) | set(WORKFLOW_DEFS.keys())
    try:
        for agent in client.agents.list():
            if agent.name in all_agent_names:
                client.agents.delete(agent.name)
                print(f"  [deleted] {agent.name}")
    except Exception as e:
        print(f"Warning: could not list/delete existing agents: {e}")

    # Build the churn scoring tool (OpenAPI) for the enriched exit-risk agent.
    scoring_tool = _build_scoring_tool()

    # Create prompt agents. All get the MongoDB MCP tool; the enriched exit-risk
    # agent additionally gets the churn scoring tool.
    print("Prompt Agents:")
    for name, instructions in AGENT_DEFS.items():
        tools = [mcp_tool]
        if name in SCORING_TOOL_AGENTS and scoring_tool is not None:
            tools = [mcp_tool, scoring_tool]
        client.agents.create_version(
            agent_name=name,
            definition=PromptAgentDefinition(
                model=MODEL,
                instructions=instructions,
                tools=tools,
            ),
        )
        suffix = "  (+ churn scoring tool)" if len(tools) > 1 else ""
        print(f"  [created] {name}{suffix}")

    # Create workflow agents (portal visibility for the sequential chain)
    print("\nWorkflow Agents:")
    for name, yaml_def in WORKFLOW_DEFS.items():
        client.agents.create_version(
            agent_name=name,
            definition=WorkflowAgentDefinition(
                workflow=yaml_def,
            ),
        )
        print(f"  [created] {name}")

    print()
    print("All agents registered in Foundry portal.")
    print()
    print("Portal agents (for visibility):")
    for name in list(AGENT_DEFS.keys()) + list(WORKFLOW_DEFS.keys()):
        print(f"  - {name}")
    print()
    print("MCP Tool (MongoDB) attached to all prompt agents via server_url.")
    print(f"  Server URL: {MCP_SERVER_URL}")
    print()
    print("NOTE: All agents are invoked at runtime via agent_reference")
    print("(Foundry Responses API) in foundry_agents.py.")
    print("Foundry handles MCP tool execution server-side.")


if __name__ == "__main__":
    main()
