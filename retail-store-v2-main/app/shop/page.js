"use client";
import React, { useState, useEffect, useCallback, useRef } from "react";
import { v4 as uuidv4 } from "uuid";

import "./shop.css";
import Navbar from "../_components/navbar/Navbar";
import ProductList from "../_components/productList/ProductList";
import ProductDetailsModal from "../_components/productDetailsModal/ProductDetailsModal";
import SearchBar from "../_components/searchBar/SearchBar";
import { DisplayMode, DrawerLayout } from "@leafygreen-ui/drawer";
import { useDispatch, useSelector } from "react-redux";
import { setIsDrawerOpen, pushCustomerBehaviourItem, setCustomerBehaviour, setChurnRisk } from "@/redux/slices/CustomerRetentionSlice";
import { COLLECTIONS } from "@/lib/constants";
import { fetchCustomerBehaviours } from "@/lib/api";
import CustomerRetentionContainer from "../_components/customerRetention/CustomerRetentionContainer";

export default function Page() {
  const dispatch = useDispatch();
  const [openHelpModal, setOpenHelpModal] = useState(false);
  const { isDrawerOpen, isCustomerRetentionEnabled } = useSelector(state => state.CustomerRetention);
  const { initialFetch, isLoading } = useSelector(state => state.CustomerRetention.customerBehaviour);
  const selectedUser = useSelector(state => state.User.selectedUser);
  const sseConnection = useRef(null);
  const churnRiskSSEConnection = useRef(null);
  const changeStreamSessionID = useRef(uuidv4());
  const churnRiskSessionID = useRef(uuidv4());

  const listenToSSEUpdates = useCallback(() => {
    const sid = sessionStorage.getItem("sid");
    const uid = selectedUser?._id;

    if (!sid || !uid) {
      console.warn("Missing sid or uid for SSE connection");
      return null;
    }

    console.log("listenToSSEUpdates func - sid:", sid, "uid:", uid);
    const eventSource = new EventSource(
      `/api/sse?sessionId=${changeStreamSessionID.current}&colName=${COLLECTIONS.CUSTOMER_BEHAVIOUR}&uid=${uid}&sid=${sid}`
    );

    eventSource.onopen = () => {
      console.log("SSE connection opened for customer behaviour events.");
    };

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log("Received SSE Update on Events:", data);
      if (data.operationType === "insert") {
        const newDocument = data.fullDocument;
        if (newDocument) {
          console.log("Received new customer behaviour document:", newDocument);
          dispatch(pushCustomerBehaviourItem(newDocument));
        }
      }
    };

    eventSource.onerror = (event) => {
      console.error("SSE Error for customer behaviour:", event);
    };

    // Close the previous connection if it exists
    if (sseConnection.current) {
      sseConnection.current.close();
      console.log("Previous SSE connection closed - customer behaviour.");
    }

    sseConnection.current = eventSource;
    return eventSource;
  }, [selectedUser, dispatch]);

  // Fetch customer behaviours on every mount of the shop page. This backfills
  // signals that fired while the user was on another page -- notably
  // cart-abandonment, which fires on the /cart page while this page (and its
  // live signal SSE) is unmounted. Without this, returning to the shop would
  // show the NBA (its SSE lives in the global navbar) but not the signal.
  useEffect(() => {
    if (selectedUser && isCustomerRetentionEnabled) {
      dispatch(setCustomerBehaviour({ initialFetch: true, isLoading: true }));
      fetchCustomerBehaviours()
        .then((response) => {
          dispatch(setCustomerBehaviour({ isLoading: false, data: response }));
        })
        .catch((error) => {
          console.error("Error fetching customer behaviours:", error);
          dispatch(setCustomerBehaviour({ isLoading: false, data: [] }));
        });
    }
  }, [selectedUser, isCustomerRetentionEnabled, dispatch]);

  // SSE connection for real-time updates (customer behaviour)
  useEffect(() => {
    if (selectedUser && isCustomerRetentionEnabled) {
      const eventSource = listenToSSEUpdates();
      return () => {
        if (eventSource) {
          eventSource.close();
          console.log("SSE connection closed - customer behaviour.");
        }
      };
    }
  }, [listenToSSEUpdates, selectedUser, isCustomerRetentionEnabled]);

  // SSE connection for churn risk predictions from Microsoft Fabric
  useEffect(() => {
    if (!selectedUser || !isCustomerRetentionEnabled) return;

    const uid = selectedUser?._id;
    const eventSource = new EventSource(
      `/api/sse?sessionId=${churnRiskSessionID.current}&colName=${COLLECTIONS.CHURN_RISK_SCORES}`
    );

    eventSource.onopen = () => {
      console.log("SSE connection opened for churn risk scores.");
    };

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.operationType === "insert" || data.operationType === "replace" || data.operationType === "update") {
        const doc = data.fullDocument;
        if (doc && doc.uid === uid) {
          console.log("Received churn risk prediction:", doc);
          dispatch(setChurnRisk(doc));
        }
      }
    };

    eventSource.onerror = (event) => {
      console.error("SSE Error for churn risk:", event);
    };

    if (churnRiskSSEConnection.current) {
      churnRiskSSEConnection.current.close();
    }
    churnRiskSSEConnection.current = eventSource;

    return () => {
      eventSource.close();
      console.log("SSE connection closed - churn risk.");
    };
  }, [selectedUser, isCustomerRetentionEnabled, dispatch]);

  // Hide scrollbar on shop page
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';

    // Cleanup on unmount
    return () => {
      document.body.style.overflow = '';
      document.documentElement.style.overflow = '';
    };
  }, []);

  if(!isCustomerRetentionEnabled){
    return <main>
          <Navbar />
          <div className="container mx-auto px-4 my-4 d-flex justify-content-between">
            <SearchBar />
          </div>
          <div className="ProductListContainer container mx-auto px-4">
            <ProductList />
          </div>
          <ProductDetailsModal />
        </main>
  }
  return (
      <DrawerLayout
        className="drawer-layout"
        displayMode={DisplayMode.Embedded}
        isDrawerOpen={isDrawerOpen}
        drawer={ <CustomerRetentionContainer /> }
        onClose={() => dispatch(setIsDrawerOpen(false))}
        size="large"
      >
        <main>
          <Navbar />
          <div className="container mx-auto px-4 my-4 d-flex justify-content-between">
            <SearchBar />
          </div>
          <div className="ProductListContainer container mx-auto px-4 mb-4">
            <ProductList />
          </div>
          <ProductDetailsModal/>
        </main>
      </DrawerLayout>
  );
}
