// Simple test to verify getAllTasks API integration
const { getAllTasks } = require('./src/lib/api.ts');

async function testGetAllTasks() {
  try {
    console.log('Testing getAllTasks API...');
    const result = await getAllTasks();
    console.log('Result:', JSON.stringify(result, null, 2));
    
    if (result.error) {
      console.error('API Error:', result.error);
    } else {
      console.log('Success! Found', result.data?.length || 0, 'tasks');
    }
  } catch (error) {
    console.error('Test failed:', error);
  }
}

testGetAllTasks();