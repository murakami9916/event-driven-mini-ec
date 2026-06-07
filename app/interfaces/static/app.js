const pretty = (value) => JSON.stringify(value, null, 2);

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await response.json();
  if (!response.ok) {
    throw data;
  }
  return data;
}

function show(id, value) {
  document.getElementById(id).textContent = pretty(value);
}

async function refreshSummary() {
  const summary = await request("/read-models/order-summary");
  document.getElementById("summary").innerHTML = `
    <span>orders: ${summary.orders_created}</span>
    <span>reserved: ${summary.inventory_reserved}</span>
    <span>rejected: ${summary.inventory_rejected}</span>
    <span>shipments: ${summary.shipments_created}</span>
  `;
  show("summary-output", summary);
}

document.getElementById("inventory-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await request("/inventory/adjustments", {
      method: "POST",
      body: JSON.stringify({
        sku: document.getElementById("inventory-sku").value,
        delta: Number(document.getElementById("inventory-delta").value),
      }),
    });
    show("inventory-output", data);
  } catch (error) {
    show("inventory-output", error);
  }
});

document.getElementById("order-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await request("/orders", {
      method: "POST",
      headers: {"Idempotency-Key": document.getElementById("idempotency-key").value},
      body: JSON.stringify({
        items: [{
          sku: document.getElementById("order-sku").value,
          quantity: Number(document.getElementById("order-quantity").value),
        }],
      }),
    });
    document.getElementById("lookup-order-id").value = data.order_id;
    show("order-output", data);
  } catch (error) {
    show("order-output", error);
  }
});

document.getElementById("lookup-order").addEventListener("click", async () => {
  try {
    const orderId = document.getElementById("lookup-order-id").value;
    show("lookup-output", await request(`/orders/${orderId}`));
  } catch (error) {
    show("lookup-output", error);
  }
});

document.getElementById("rebuild").addEventListener("click", async () => {
  try {
    const result = await request("/admin/projections/order-summary/rebuild", {method: "POST"});
    show("summary-output", result);
    await refreshSummary();
  } catch (error) {
    show("summary-output", error);
  }
});

document.getElementById("refresh").addEventListener("click", refreshSummary);

document.querySelectorAll("[data-target][data-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      const {target, action} = button.dataset;
      show("fault-output", await request(`/admin/faults/${target}/${action}`, {method: "POST"}));
    } catch (error) {
      show("fault-output", error);
    }
  });
});

refreshSummary().catch((error) => show("summary-output", error));

