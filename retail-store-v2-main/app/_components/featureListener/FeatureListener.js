'use client';

import { useEffect } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { useDispatch, useSelector } from 'react-redux';
import { setFeature } from '@/redux/slices/GlobalSlice';
import { FEATURES } from '@/lib/constants';
import { setIsCustomerRetentionEnabled } from '@/redux/slices/CustomerRetentionSlice';

export default function FeatureListener() {
  const dispatch = useDispatch();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const featureInStore = useSelector((state) => state.Global.feature);

  useEffect(() => {
    const featureParam = searchParams.get('feature') || null;
    // Keep the feature sticky: if a page is navigated to without the ?feature=
    // param, fall back to the feature already in the store instead of clearing
    // it. Without this, any navigation to a param-less URL (e.g. bouncing to the
    // cart and back) silently disables the customer-retention panel. A URL that
    // DOES carry a feature param always wins, so switching features still works.
    const effectiveFeature = featureParam || featureInStore || null;
    console.log('🛠 FeatureListener feature param:', featureParam, '-> effective:', effectiveFeature);

    if (effectiveFeature !== featureInStore) {
      dispatch(setFeature({feature: effectiveFeature}));
      console.log('🛠 FeatureListener dispatched setFeature:', effectiveFeature);
    }
    dispatch(setIsCustomerRetentionEnabled({ isCustomerRetentionEnabled: effectiveFeature === FEATURES.CUSTOMER_RETENTION }) );
  }, [searchParams.toString(), pathname]);

  return null; // no UI, just listener
}
