// Script to verify that chat messages create tasks
// Run this while you're chatting to see if tasks are created

const API_BASE = 'http://localhost:8000'; // Backend API URL

async function checkRecentTasks() {
  try {
    console.log('🔍 Checking for recent tasks...\n');

    // Get all agents first
    const agentsResponse = await fetch(`${API_BASE}/v1/agents/`);
    if (!agentsResponse.ok) {
      throw new Error('Failed to fetch agents');
    }
    const agents = await agentsResponse.json();
    
    console.log(`Found ${agents.length} agents`);
    
    // Check tasks for each agent
    let totalTasks = 0;
    for (const agent of agents) {
      console.log(`\n📋 Agent: ${agent.name} (${agent.id})`);
      
      try {
        const tasksResponse = await fetch(`${API_BASE}/v1/agents/${agent.id}/tasks/`);
        if (tasksResponse.ok) {
          const tasks = await tasksResponse.json();
          console.log(`   Tasks: ${tasks.length}`);
          totalTasks += tasks.length;
          
          // Show recent tasks (last 3)
          const recentTasks = tasks.slice(-3);
          recentTasks.forEach((task, index) => {
            console.log(`   ${index + 1}. ${task.description} (${task.status}) - ${task.created_at}`);
          });
        } else {
          console.log(`   ⚠️  Could not fetch tasks (${tasksResponse.status})`);
        }
      } catch (err) {
        console.log(`   ❌ Error fetching tasks: ${err.message}`);
      }
    }
    
    console.log(`\n📊 Total tasks across all agents: ${totalTasks}`);
    
    if (totalTasks === 0) {
      console.log('\n💡 No tasks found. Try sending a message in the chat and run this script again.');
    }
    
  } catch (error) {
    console.error('❌ Error:', error.message);
  }
}

// Run every 5 seconds to monitor for new tasks
console.log('🚀 Starting task monitor... (Press Ctrl+C to stop)');
console.log('💬 Send messages in the chat and watch for new tasks!\n');

checkRecentTasks();
setInterval(checkRecentTasks, 5000);