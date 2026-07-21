"use client";

import Link from "next/link";
import { useSelector } from "react-redux";
import IconButton from "@leafygreen-ui/icon-button";

// Top-level cart button for the main navbar. Kept separate from the Profile
// dropdown so the cart behaves like a standard storefront: always one click
// away, with a live item-count badge. The count reflects the same Redux cart
// state the cart page reads.
const CartButton = () => {
  const featureInStore = useSelector((state) => state.Global.feature);
  const cartCount = useSelector((state) => state.User.cart?.products?.length || 0);

  const href = featureInStore ? `/cart?feature=${featureInStore}` : "/cart";

  return (
    <div className="cartButtonContainer">
      <Link href={href} aria-label="My Cart">
        <IconButton className={"NavbarButtonIcon"} aria-label="My Cart">
          <img
            src="/rsc/icons/cart-shopping-solid.svg"
            alt="Shopping cart"
            width={18}
          />
        </IconButton>
      </Link>
      {cartCount > 0 && (
        <span className="cartCountBadge" aria-label={`${cartCount} items in cart`}>
          {cartCount}
        </span>
      )}
    </div>
  );
};

export default CartButton;
