// Simple test script to verify task detail implementation
const puppeteer = require('puppeteer');

async function testTaskDetail() {
  const browser = await puppeteer.launch({ headless: false });
  const page = await browser.newPage();
  
  try {
    // Navigate to the tasks page
    await page.goto('http://localhost:3000/agents/tasks');
    await page.waitForSelector('table', { timeout: 10000 });
    
    console.log('✓ Tasks page loaded successfully');
    
    // Check if there are any tasks in the table
    const taskRows = await page.$$('tbody tr');
    
    if (taskRows.length > 0) {
      console.log(`✓ Found ${taskRows.length} tasks in the table`);
      
      // Click on the first task to navigate to detail page
      await taskRows[0].click();
      
      // Wait for navigation to task detail page
      await page.waitForNavigation();
      
      // Check if we're on a task detail page
      const url = page.url();
      if (url.includes('/agents/tasks/')) {
        console.log('✓ Successfully navigated to task detail page:', url);
        
        // Wait for the task detail content to load
        await page.waitForSelector('h1', { timeout: 10000 });
        
        // Check for key elements that should be present
        const title = await page.$eval('h1', el => el.textContent);
        console.log('✓ Task title loaded:', title);
        
        // Check for tabs
        const tabs = await page.$$('[role="tablist"] button');
        console.log(`✓ Found ${tabs.length} tabs in task detail`);
        
        // Check for loading states or error states
        const loadingElement = await page.$('[data-testid="loading"]');
        const errorElement = await page.$('[data-testid="error"]');
        
        if (loadingElement) {
          console.log('⚠ Task is still loading');
        } else if (errorElement) {
          console.log('⚠ Task detail shows error state');
        } else {
          console.log('✓ Task detail loaded successfully without errors');
        }
        
      } else {
        console.log('✗ Failed to navigate to task detail page');
      }
    } else {
      console.log('⚠ No tasks found in the table - cannot test navigation');
    }
    
  } catch (error) {
    console.error('✗ Test failed:', error.message);
  } finally {
    await browser.close();
  }
}

// Run the test
testTaskDetail().catch(console.error);