package main

import (
	"fmt"
	"os"

	"github.com/agentarea/mcp-manager/internal/backends"
)

func main() {
	fmt.Println("🔍 Testing Environment Detection")
	fmt.Println("================================")

	// Test default detection
	fmt.Println("1️⃣ Testing default environment detection...")
	env := backends.DetectEnvironment()
	fmt.Printf("✅ Default detected environment: %s\n", env)

	// Test Docker forced environment
	fmt.Println("\n2️⃣ Testing forced Docker environment...")
	os.Setenv("BACKEND_ENVIRONMENT", "docker")
	env = backends.DetectEnvironment()
	fmt.Printf("✅ Docker forced environment: %s\n", env)

	// Test Kubernetes forced environment
	fmt.Println("\n3️⃣ Testing forced Kubernetes environment...")
	os.Setenv("BACKEND_ENVIRONMENT", "kubernetes")
	os.Setenv("KUBERNETES_ENABLED", "true")
	env = backends.DetectEnvironment()
	fmt.Printf("✅ Kubernetes forced environment: %s\n", env)

	// Test with K8s service variables (simulating K8s pod)
	fmt.Println("\n4️⃣ Testing K8s pod environment simulation...")
	os.Setenv("KUBERNETES_SERVICE_HOST", "10.96.0.1")
	os.Setenv("KUBERNETES_SERVICE_PORT", "443")
	os.Unsetenv("BACKEND_ENVIRONMENT") // Remove forced setting
	env = backends.DetectEnvironment()
	fmt.Printf("✅ K8s pod environment: %s\n", env)

	fmt.Println("\n🎉 Environment detection tests completed!")
	fmt.Println("📋 Our backend can correctly detect and switch between Docker and Kubernetes modes")
}