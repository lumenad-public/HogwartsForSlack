# LumenAd-Hogwarts
A custom app for distributing points via slash commands in Slack

# Introduction
Do you want to be a wizard like Harry Potter and go to Hogwarts?  
Well I probably can't help you with that, but I can help you bring a bit of magic to your company with this tutorial.
If you follow these instructions you'll be able to have your very House Cup app in Slack!
You can give points to your friends and colleagues who take time out of their day to help you out.
You can take points when someone double-books the conference room.  
You can even have award a winning house at your Holiday party (trophy not included).  This repo will teach you what you need to know.   
![AWS Sign In](/images/house_cup_2018.png)

# What you'll need
* An AWS (Amazon Web Services) Account - I recommend using a separate AWS account if you already have production resources in AWS
* Slack and enough priviledges to create custom Slash commands - ask your IT specialist if you don't have this
* Some familiarity with Python - Harry Potter wasn't afraid to confront a giant snake and you shouldn't be either

# The Database
First you'll need to log in to your AWS account or create an account: https://aws.amazon.com
AWS (Amazon Web Services) is Amazon's cloud computing suite.  It's pretty easy to get started and they handle a lot of the crummiest parts of software development.  Even if you have no familiarity with AWS you can complete this tutorial.  

![AWS Sign In](/images/aws_sign_in.png)

If you don't have an account yet be aware that you have to provide a credit card during creation.  Even though most of this will fall within the Free Tier usage you should be aware that you can accrue charges if something is misconfigured.  **LumenAd takes no responsibility for unexpected AWS bills.**  After the Free Tier is over (new accounts have access to the Free Tier for 1 year) the charges are still pretty small.  LumenAd has over 60 employees registered and the app gets tons of use, but the monthly bill for the service and database is only about $3.

After you're logged in you're ready to create a DynamoDB table.  Navigate to Services from the main page and search for `DynamoDB` then select it from the dropdown. I chose DynamoDB to make development of new features easier and because I wanted to learn the technology for another project.  If you're more familiar with a different database you can easily switch it out here. I recommend staying within the AWS environment for this step as Lambda functions connect very easily to AWS databases.
![AWS Services](/images/aws_search_services.png)

From the DynamoDB service page click `Create Table`.
![AWS DynamoDB table](/images/aws_create_dynamodb_table.png)

The database configuraton options here are pretty varied, but I recommend using the slack username as your Primary Key accepting the default settings.  If you want to get fancy you can add a Sort Key and Secondary Indexes to improve query efficiency and speed.  However I only recommend doing this if you both know what you're doing and plan on having tons of users.  If you have <1000 users I wouldn't worry about it.

![AWS DynamoDB Settings](/images/aws_dynamnodb_table_config.png)

Once you have your table created you can begin adding items.  You can get very creative with the attributes of your users, but for this tutorial I recommend 5:
* `name` - String - the username provided by slack.  You can include the @ if you want, but I've chosen to parse that out.
* `fullname` - String - The full name of the user.  This one isn't completely necessary, but it helps make the responses readable.
* `house` - String - the house the user belongs to:  Gryffindor, Slytherin, Ravenclaw or Hufflepuff.
* `points` - Float/Decimal - the number of points the user has. Everyone will start with 0.
* `can_has` - Boolean -  a special flag so you can disable users without having to shut the whole app down. You can rename this to something more sensible, but we are building a Harry Potter app here so don't take it too seriously.
Optionals:
* `nickname` - Allows you to assign a nickname to users.  Turn `Calvin Broadus` into `Calvin "Snoop Dogg" Broadus`.
* `title` - Allows you to assign a title to a user.  Turn `Daenerys Targaryen` into `Daenerys Targaryen, the First of Her Name, The Unburnt, Queen of the Andals, the Rhoynar and the First Men, Queen of Meereen, Khaleesi of the Great Grass Sea, Protector of the Realm, Lady Regent of the Seven Kingdoms, Breaker of Chains and Mother of Dragons`.

You may be wondering where to set these attributes in DynamoDB.  The answer is nowhere.  DynamoDB is a NoSQL database meaning it's unstructured.  For the uninitiated that means you can have highly varied data all in the same table.  In our example you could have a row with 3 attributes and a row with 30 attributes so long as they both have valid Primary Keys.  The easiest way to set this up is to store the data of your members with the attributes you want filled out then upload the data to DynamoDB.   
# Populating the Database
The one part of this whole process I haven't come with a good solution to is putting everyone in houses.  When I did this I had to go around to everyone in the company and ask what house they'd like to be in and keep track in a .csv file.  This was kind of a pain, but there's not really any other way to do it.  

You could have people fill out their own houses, but I had a hard time just getting everyone to come up with a house, let alone write it down.  There's also an option to put everyone in the database then create a command that lets them move themselves.  I didn't do this because I thought people would be switching all the time, but that may be a better solution for you.  Either way you'll need a default house for everyone who can't decide. I chose Hufflepuff as the default because of a quote from the books: <em>"Good Hufflepuff, she took the rest and taught them all she knew"</em>

Here's the original javascript I used to upload the data to DynamoDB from a csv.  Depending on how you collect and store you data you may be able to use this snippet unmodified or you may need something completely different.  This is more to give you an idea of how I did it.  May it help you in your travels.
```const fs = require('fs')
const parse = require('csv-parse/lib/sync')
const AWS = require('aws-sdk')

AWS.config.update({ region: 'us-east-2' });
const docClient = new AWS.DynamoDB.DocumentClient()

const contents = fs.readFileSync('./hp.csv', 'utf-8')
// If you made an export of a DynamoDB table you need to remove (S) etc from header
const data = parse(contents, {columns: true})

data.forEach((item) => {
        if(!item.maybeempty) delete item.maybeempty //need to remove empty items
        //console.log(item)
        item['points'] = 0;
        item['can_has'] = true;
        docClient.put({TableName: 'Hogwarts', Item: item}, (err, res) => {
                if(err) console.log(err)
        })
})
```

Alternatively you can enter each user manually through the UI.  Select `Create Item` on your table.
![AWS DynamoDB Settings](/images/aws_dynamodb_create_item.png)

Then you can enter your users' information via the `Tree` editor or the `JSON` editor.  This would be pretty laborious if you were gonna add 50 users, but if you've only got a few users this may be easier than attempting an automated upload.
NOTE: You don't need to add `title` or `nickname` to users, the code provided works without it and you can add them later.
![AWS DynamoDB Settings](/images/aws_dynamodb_item.png)


# The Code - Lambda
![AWS Lambda](/images/aws_lambda_service.png)
This part is pretty straightforward.  Navigate to AWS Lambda from the Services dropdown in the top bar and select `Create Function`.  Select `Author from Scratch` and enter a name for your function.  The name doesn't matter, but keep it short because it'll end up as a url parameter later.  For a Runtime select `Python 3.6`.  As for Permissions this part can get a little tricky depending on how your AWS account is configured. You'll need an AWS user role that can execute lambda function and full access for DynamoDB at a minimum, but I also added full Cloudwatch permissions because it's super helpful for debugging.  Whether you want to create that role ahead of time or add the permissions to the role created in this step is up to you.  
![AWS Lambda Create Function](/images/aws_lambda_create_function.png)

The one catch here is to make sure you use the same region as your database to make connecting easier.  You can use the code I've provided with this repository and as long as the names of your attributes and tables match it should be plug and play.  You will need to add your Slack key as an environment variable in a later step.
![AWS Lambda Create Function](/images/aws_lambda_code.png)

Finally we need to attach an http endpoint to our new Lambda function.  Select `Add Trigger` in the Lambda Designer panel and select `API Gateway`.  
![AWS Lambda Create Trigger](/images/aws_lambda_create_trigger.png)

API Gateway will create an endpoint for your function that you can call with a simple http request.  This is the magic that allows you to execute the command via Slack.  You can create a new API in this step or select an existing one if you happen to have an AWS API lying around.  The Deployment Stage doesn't really matter since we likely won't have many different versions of this function.  Under Security select `Open`.  Normally I would never recommend this as it allows any resource with access to the url to call your function.  However, this is the only way to make it work via a Slack command and we'll add our own security to it in a later step.
![AWS Lambda Trigger Config](/images/aws_lambda_trigger_config.png)

# Slack Integration
Head on over to https://api.slack.com/apps and select `Create New App`, give your app a name (I recommend either Hogwarts or Dumbledore full full effect) and select the workspace you want the app to be active in. After creating your app select `Slash Commands` then select `Create New Command`.
![Slack Create App](/images/slack_create_app.png)

For the command I recommend either `/points` or `/hogwarts`.  In `Request URL` put the URL generated by the API Gateway trigger in the previous step.  You can put a short description and a usage hint (/points @user <number>) to remind users how the whole thing works.  
![Slack Slash Commands](/images/slack_slash_command.png)

After completing the slash command scroll towards the bottom until you find a section called `App Credentials`.  Copy the value from `Signing Secret`.  Return to AWS to paste that value into the environment variable section as `SLACK_KEY`.
![AWS Lambda Environment Variable](/images/aws_lambda_slack_key.png)

Finally navigate back up and select `Install your app to your Workspace`.

# Testing
If everything worked you should now be able to open Slack and give some people some points. I recommend testing in a private channel so people won't see any errors.  If something is wrong you can hop over to AWS CloudWatch and check the Logs.  The logs from your Lambda function will appear under Logs with the link `/aws/lambda/<whatever you called your Lambda function>`.
![AWS Lambda Environment Variable](/images/aws_cloudwatch_logs.png)

# Conclusion
Congratulations!  You've now got a functioning AWS Lambda/Slack integration and the wizarding world at your fingertips.  Now get out there and represent your house!  

- Kegan, LumenAd Headmaster, Data Scientist
