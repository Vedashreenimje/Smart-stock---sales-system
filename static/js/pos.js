document.addEventListener("DOMContentLoaded", () => {
    let cart = [];
    const productsGrid = document.getElementById("productsGrid");
    const cartItems = document.getElementById("cartItems");
    const emptyCartMessage = document.getElementById("emptyCartMessage");
    const subtotalEl = document.getElementById("subtotal");
    const totalEl = document.getElementById("total");
    const checkoutBtn = document.getElementById("checkoutBtn");
    const searchInput = document.getElementById("searchInput");

    // 1. INITIAL DISPLAY: Show all products when page loads
    if (window.ALL_PRODUCTS) {
        renderProducts(window.ALL_PRODUCTS);
    }

    // 2. SEARCH FUNCTION: Filter by name, ID, or Category
    searchInput.addEventListener("input", (e) => {
        const term = e.target.value.toLowerCase();
        const filtered = window.ALL_PRODUCTS.filter(p => 
            p.name.toLowerCase().includes(term) || 
            p.id.toString().includes(term) ||
            (p.category_name && p.category_name.toLowerCase().includes(term))
        );
        renderProducts(filtered);
    });

    // 3. RENDER PRODUCTS: Create the HTML cards
    function renderProducts(products) {
        productsGrid.innerHTML = "";
        if (products.length === 0) {
            productsGrid.innerHTML = '<div class="col-12 text-center py-5 text-muted">No products found.</div>';
            return;
        }

        products.forEach(p => {
            const isLowStock = p.stock_quantity <= 0;
            const card = document.createElement("div");
            card.className = "col-md-4 mb-3";
            card.innerHTML = `
                <div class="card shadow-sm h-100 product-card ${isLowStock ? 'opacity-50' : ''}" id="prod-${p.id}">
                    <div class="card-body text-center p-2">
                        <small class="text-muted d-block mb-1">${p.category_name || 'General'}</small>
                        <h6 class="fw-bold mb-1 text-truncate">${p.name}</h6>
                        <p class="text-success fw-bold mb-1">₹${parseFloat(p.selling_price).toFixed(2)}</p>
                        <small class="badge ${p.stock_quantity < 5 ? 'bg-danger' : 'bg-light text-dark'} mb-2">
                            Stock: ${p.stock_quantity}
                        </small>
                        <button class="btn btn-sm btn-primary w-100 add-btn" ${isLowStock ? 'disabled' : ''}>
                            ${isLowStock ? 'Out of Stock' : 'Add to Cart'}
                        </button>
                    </div>
                </div>
            `;
            if (!isLowStock) {
                card.querySelector(".add-btn").onclick = () => addToCart(p);
            }
            productsGrid.appendChild(card);
        });
    }

    // 4. ADD TO CART: Handle the logic of adding items
    function addToCart(product) {
    const existingItem = cart.find(item => item.id === product.id);

    if (existingItem) {
        if (existingItem.quantity < product.stock_quantity) {
            existingItem.quantity++;
        } else {
            alert(`Cannot add more. Only ${product.stock_quantity} units in stock!`);
            return;
        }
    } else {
        cart.push({
            id: product.id,
            name: product.name,
            price: parseFloat(product.selling_price),
            quantity: 1
        });

        // 🔥 AI INTEGRATION: Fetch "Bought Together" suggestions
        fetch(`/api/ai/recommendations/${product.id}`)
            .then(res => res.json())
            .then(suggestions => {
                if(suggestions.length > 0) {
                    showAiSuggestion(suggestions[0], product.name);
                }
            })
            .catch(err => console.log("AI Suggestion error:", err));
    }

    // Visual feedback: brief highlight on the card
    const card = document.getElementById(`prod-${product.id}`);
    if(card) {
        card.classList.add('border-primary', 'shadow');
        setTimeout(() => card.classList.remove('border-primary', 'shadow'), 300);
    }

    updateCartUI();
}

// 💡 New helper function to display the AI suggestion in the UI
function showAiSuggestion(suggested, triggerName) {
    const cartItems = document.getElementById("cartItems");
    const toast = document.createElement("div");
    toast.className = "alert alert-info border-0 shadow-sm mx-2 mt-2 animate__animated animate__fadeInUp";
    toast.style.fontSize = "0.85rem";
    toast.innerHTML = `
        <div class="d-flex justify-content-between align-items-center">
            <span>💡 <strong>AI Tip:</strong> With <em>${triggerName}</em>, people also buy <strong>${suggested.name}</strong></span>
            <button class="btn btn-sm btn-primary py-0" onclick='addToCartFromAi(${JSON.stringify(suggested)})'>Add</button>
        </div>
    `;
    // Insert it at the top of the cart items list
    cartItems.prepend(toast);
    
}

// Helper to handle adding from the AI suggestion link
window.addToCartFromAi = (p) => {
    // Find the full product object from your main list to ensure we have stock info
    const fullProduct = window.ALL_PRODUCTS.find(item => item.id === p.id);
    if(fullProduct) {
        addToCart(fullProduct);
        // Remove the suggestion box once added
        event.target.closest('.alert').remove();
    }
};

    // 5. UPDATE UI: Show the items in the right-side cart
    function updateCartUI() {
        cartItems.innerHTML = "";
        let total = 0;

        if (cart.length === 0) {
            cartItems.appendChild(emptyCartMessage);
            checkoutBtn.disabled = true;
        } else {
            checkoutBtn.disabled = false;
            cart.forEach((item, index) => {
                const sub = item.price * item.quantity;
                total += sub;
                
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td class="py-2">
                        <div class="fw-bold small">${item.name}</div>
                        <small class="text-muted">${item.quantity} x ₹${item.price.toFixed(2)}</small>
                    </td>
                    <td class="text-end py-2">
                        <div class="fw-bold small">₹${sub.toFixed(2)}</div>
                        <button class="btn btn-sm text-danger p-0" style="font-size: 0.75rem" onclick="removeFromCart(${index})">Remove</button>
                    </td>
                `;
                cartItems.appendChild(tr);
            });
        }

        subtotalEl.textContent = total.toFixed(2);
        totalEl.textContent = total.toFixed(2);
    }

    // Global function to remove items
    window.removeFromCart = (index) => {
        cart.splice(index, 1);
        updateCartUI();
    };

    // 6. CHECKOUT: Send cart data to Python backend
    checkoutBtn.onclick = () => {
        const paymentMode = document.querySelector("input[name='paymentMode']:checked").value;

        const saleData = {
            items: cart,
            total: parseFloat(totalEl.textContent),
            payment_mode: paymentMode
        };

        checkoutBtn.disabled = true;
        checkoutBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Processing...';

        fetch("/create_sale", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(saleData)
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                // SUCCESS: Notify user
                alert(`✅ Sale Successful!\nInvoice: ${data.invoice}`);
                
                // Optional: Print Receipt
                if (confirm("Do you want to open the receipt?")) {
                    window.open(`/receipt/${data.sale_id}`, '_blank');
                }
                
                location.reload(); 
            } else {
                alert("❌ Error: " + data.error);
                checkoutBtn.disabled = false;
                checkoutBtn.innerHTML = "✅ Complete Sale";
            }
        })
        .catch(err => {
            console.error("Checkout Error:", err);
            alert("Server connection failed!");
            checkoutBtn.disabled = false;
            checkoutBtn.innerHTML = "✅ Complete Sale";
        });
    };

    // Clear Cart Helper
    window.clearCart = () => {
        if(cart.length > 0 && confirm("Are you sure you want to clear the cart?")) {
            cart = [];
            updateCartUI();
        }
    };
});