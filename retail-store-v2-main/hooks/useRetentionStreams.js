import { useCallback, useEffect, useRef } from "react";
import { useDispatch, useSelector } from "react-redux";
import { v4 as uuidv4 } from "uuid";

import { COLLECTIONS } from "@/lib/constants";
import { fetchCustomerBehaviours } from "@/lib/api";
import {
  pushCustomerBehaviourItem,
  setCustomerBehaviour,
  setChurnRisk,
} from "@/redux/slices/CustomerRetentionSlice";

/**
 * Subscribes to the customer-retention real-time streams for the current page:
 *  - session_signals SSE  -> behaviour signals panel (live)
 *  - churn_risk_scores SSE -> Fabric churn panel (live)
 *  - a backfill fetch on mount so signals that fired while the user was on
 *    another page (e.g. cart-abandonment fires on /cart) are pulled in.
 *
 * Used by both the shop and cart pages so the retention panel behaves the same
 * wherever it is shown. Guarded by the retention feature + a selected user.
 */
export default function useRetentionStreams() {
  const dispatch = useDispatch();
  const selectedUser = useSelector((state) => state.User.selectedUser);
  const { isCustomerRetentionEnabled } = useSelector(
    (state) => state.CustomerRetention
  );

  const signalSSE = useRef(null);
  const churnSSE = useRef(null);
  const signalSessionID = useRef(uuidv4());
  const churnSessionID = useRef(uuidv4());

  const listenToSignals = useCallback(() => {
    const sid = sessionStorage.getItem("sid");
    const uid = selectedUser?._id;
    if (!sid || !uid) return null;

    const eventSource = new EventSource(
      `/api/sse?sessionId=${signalSessionID.current}&colName=${COLLECTIONS.CUSTOMER_BEHAVIOUR}&uid=${uid}&sid=${sid}`
    );
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.operationType === "insert" && data.fullDocument) {
        dispatch(pushCustomerBehaviourItem(data.fullDocument));
      }
    };
    eventSource.onerror = (e) => console.error("SSE Error (signals):", e);

    if (signalSSE.current) signalSSE.current.close();
    signalSSE.current = eventSource;
    return eventSource;
  }, [selectedUser, dispatch]);

  // Backfill behaviour signals on mount (covers signals that fired off-page).
  useEffect(() => {
    if (selectedUser && isCustomerRetentionEnabled) {
      dispatch(setCustomerBehaviour({ initialFetch: true, isLoading: true }));
      fetchCustomerBehaviours()
        .then((response) =>
          dispatch(setCustomerBehaviour({ isLoading: false, data: response }))
        )
        .catch((error) => {
          console.error("Error fetching customer behaviours:", error);
          dispatch(setCustomerBehaviour({ isLoading: false, data: [] }));
        });
    }
  }, [selectedUser, isCustomerRetentionEnabled, dispatch]);

  // Live session_signals stream.
  useEffect(() => {
    if (selectedUser && isCustomerRetentionEnabled) {
      const es = listenToSignals();
      return () => {
        if (es) es.close();
      };
    }
  }, [listenToSignals, selectedUser, isCustomerRetentionEnabled]);

  // Live churn_risk_scores stream (Fabric panel).
  useEffect(() => {
    if (!selectedUser || !isCustomerRetentionEnabled) return;
    const uid = selectedUser?._id;
    const eventSource = new EventSource(
      `/api/sse?sessionId=${churnSessionID.current}&colName=${COLLECTIONS.CHURN_RISK_SCORES}`
    );
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (
        data.operationType === "insert" ||
        data.operationType === "replace" ||
        data.operationType === "update"
      ) {
        const doc = data.fullDocument;
        if (doc && doc.uid === uid) dispatch(setChurnRisk(doc));
      }
    };
    eventSource.onerror = (e) => console.error("SSE Error (churn):", e);

    if (churnSSE.current) churnSSE.current.close();
    churnSSE.current = eventSource;
    return () => eventSource.close();
  }, [selectedUser, isCustomerRetentionEnabled, dispatch]);
}
