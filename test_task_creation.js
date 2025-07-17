// Test script to create tasks directly via API
// Run this with: node test_task_creation.js

const API_BASE = 'http://localhost:8000'; // Backend API URL

async function testTaskCreation() {
  try {
    console.log('🚀 Testing task creation...\n');

    // Step 1: Get available agents
    console.log('1. Fetching available agents...');
    const agentsResponse = await fetch(`${API_BASE}/v1/agents/`);
    
    if (!agentsResponse.ok) {
      throw new Error(`Failed to fetch agents: ${agentsResponse.status}`);
    }
    
    const agents = await agentsResponse.json();
    console.log(`✅ Found ${agents.length} agents`);
    
    if (agents.length === 0) {
      console.log('❌ No agents available. Please create an agent first.');
      return;
    }

    // Use the first available agent
    const agent = agents[0];
    console.log(`📋 Using agent: ${agent.name} (ID: ${agent.id})\n`);

    // Step 2: Create a test task
    console.log('2. Creating a test task...');
    const taskData = {
      description: "Test task: What is the current time and date?",
      parameters: {
        priority: "normal",
        timeout: 300
      },
      user_id: "test_user",
      enable_agent_communication: true
    };

    const taskResponse = await fetch(`${API_BASE}/v1/agents/${agent.id}/tasks/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(taskData)
    });

    if (!taskResponse.ok) {
      const errorText = await taskResponse.text();
      throw new Error(`Failed to create task: ${taskResponse.status} - ${errorText}`);
    }

    const task = await taskResponse.json();
    console.log(`✅ Task created successfully!`);
    console.log(`   Task ID: ${task.id}`);
    console.log(`   Status: ${task.status}`);
    console.log(`   Execution ID: ${task.execution_id}`);
    console.log(`   Created: ${task.created_at}\n`);

    // Step 3: Check task status
    console.log('3. Checking task status...');
    const statusResponse = await fetch(`${API_BASE}/v1/agents/${agent.id}/tasks/${task.id}/status`);
    
    if (statusResponse.ok) {
      const status = await statusResponse.json();
      console.log(`✅ Task status retrieved:`);
      console.log(`   Status: ${status.status}`);
      console.log(`   Execution ID: ${status.execution_id}`);
      if (status.start_time) console.log(`   Started: ${status.start_time}`);
      if (status.end_time) console.log(`   Ended: ${status.end_time}`);
      if (status.error) console.log(`   Error: ${status.error}`);
      if (status.message) console.log(`   Message: ${status.message}`);
    }

    console.log(`\n🎉 Test completed! You can now view the task in the UI:`);
    console.log(`   Frontend URL: http://localhost:3000/agents/tasks/${task.id}`);
    console.log(`   Tasks List: http://localhost:3000/agents/tasks`);

  } catch (error) {
    console.error('❌ Test failed:', error.message);
  }
}

// Run the test
testTaskCreation();