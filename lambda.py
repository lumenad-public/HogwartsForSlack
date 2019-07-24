import os
import boto3 # AWS module for connecting to other services like DynamoDB
import json
from urllib.parse import parse_qs # small import to make parsing the request parameters easier
import datetime
import hashlib,hmac # Used for message verification

print('Loading function')
# instantiate DyanmoDB
dynamo = boto3.resource('dynamodb')

# parse Slack secert key from environment variable.
# If you're making one of these yourself don't store the key inline.
# Instead set an environment variable in Lambda and parse it like this
SLACK_KEY = bytes(os.environ["SLACK_KEY"], 'utf-8')

# A bit hacky, but a simple way to keep track of who has admin privileges.
# put your own Slack name here to become headmaster.
ADMIN = ['your_name_here']

# The houses -- used for printing out the points of each house.
HOUSES = ["gryffindor","slytherin","ravenclaw","hufflepuff"]

# Slightly hacky again -- prefixes used for displaying the point totals of all houses
PREFIXES = ["In the lead is ","Second place is ","Third place is ","Fourth place is "]

# Response wrapper -- send whatever we get back as appropriate json response
def respond(err, res=None):
    res["response_type"] = "in_channel"
    return {
        'statusCode': '400' if err else '200',
        'body': err.message if err else json.dumps(res),
        'headers': {
            'Content-Type': 'application/json',
        },
    }

# Sets a minimum of -2000 points and a maximum of 2000 points.
# People try to give/take 1000000000000000 points if you let them.
def cleanPoints(p):
    if p < 0:
        return max(-2000,p)
    else:
        return min(2000,p)

# Handler for showing the point totals for each house
def formatPoints(house_points):
    # house_points is a dictionary with structure: {'house_name': point_total}
    # The line below sorts the dictionary by point_total and creates a new sorted dictionary
    sorted_points = {k:house_points[k] for k in sorted(house_points, key=house_points.get, reverse=True)} # reversed because it normally goes in ascending order
    # Format the prefixes defind in the header section with the newly created sorted point dictionary
    report = ""
    # You know your Python is fancy when you bust out the zip() function
    for f,(h,p) in zip(PREFIXES,sorted_points.items()):
        report += "_{}{} with {} points_\n".format(f,h.capitalize(),p)
    return report

# Have you heard the tragedy of fullNameify?
# It's not a story developers would tell you.
# Ironic, it could give good names to others, but not itself.
def fullNameify(item):
    fname = item['fullname'] if 'fullname' in item else item['name']
    # You'll notice here that I attempt to parse out a 'title' and 'nickname' attribute.
    # These are totally optional, but you can add them to your users to spice up commands.
    # It's one thing to give @soren points.
    # It's another thing to give them to Soren "Teach-me-how-to-Diggery", the Prefect of Hufflepuff
    if 'nickname' in item:
        # include the nickname if they have one
        first_name, last_name = fname.split(" ")
        fname = '{} "{}" {}'.format(first_name,item['nickname'],last_name)
    if 'title' in item:
        # Include their title if the user has one
        fname = "{} the {}".format(fname,item['title'])
    return fname

# All important permissions function.
# This looks up a user by their Slack name in our DynamoDB table
# then returns their permissions and full name for future use
def checkUserPermissions(table,user):
    try:
        response = table.get_item(
            Key={
                'name': user
            },
        )
        #print(response)
        item = response['Item']
        # can_has is a catch-all permission value that prevents a user from doing anything.
        # Think of it as Hogwarts time-out.
        can_has = item['can_has']
        # Parse the fullname
        fname = fullNameify(item)
        return True, can_has, "_{}_".format(fname)
    except Exception as e:
        print(e)
        return False, False, user # If something goes wrong return false for all permissions

# Simple function that iterates over the house list defined in the header
# and saves their point totals in a dictionary.
# This creates the point dictionary used in formatPoints()
def getHouseTotals(table):
    house_points = {}
    for h in HOUSES:
        try:
            # NOTE: scan is generally an inefficient operation in DynamoDB
            # since it has to read every row in the database to compare against the
            # scan condition.  However, we've only got about 60-70 rows so far and they're all
            # really small so for now this is fine.
            # If you wanted to make this for a company of 1500 you may want to consider
            # making the house a Secondary-Index and performing a query instead of a scan.
            response = table.scan(
                FilterExpression=boto3.dynamodb.conditions.Attr("house").eq(h)
            )
            items = response['Items']
            house_points[h] = sum([i['points'] for i in items])
        except Exception as e:
            print(e)
            house_points[h] = "Error: {}".format(e)
    return house_points


# THE BIG ONE
# This is where the magic happens.
# pun intended.
def allocatePoints(table,user,points,assigner,msg):
    # First retrieve the user object from the database
    # to get their house.
    response = table.get_item(
        Key={
            'name': user
        },
    )
    item = response['Item']
    house = item['house']
    # Next clean the points* *
    # * Admins can give or take away however many points they please
    #       This was helpful for when we did Game of Thrones death-betting and people
    #       win or lose 10,000 points at a time.
    # * Anyone can give or take unlimited points from platform house
    if assigner not in ADMIN:
        points = cleanPoints(points)
    try:
        # Retrieve the permissions for both the person being given points
        # AND the person giving the points
        assigner_found, assigner_permission, fancy_assigner = checkUserPermissions(table,assigner)
        assignee_found, assignee_permission, fancy_user = checkUserPermissions(table,user)
        # format the response message that Slack will display after successful point allocation
        action = "awarded {} points to {}".format(points,fancy_user) if points > 0 else "detracted {} points from {}".format(abs(points),fancy_user)
        if assigner_permission and assignee_permission and assignee_found:
            # If all necessary permissions are met then we begin the point allocation process
            # First we allocate the points to the user.
            # Note: this seems to only give points, but the point value can be negative so this handles giving and taking away points
            response = table.update_item(
                Key={
                    'name': user
                },
                UpdateExpression="set points = points + :p",
                ExpressionAttributeValues={
                    ':p': points,
                },
                ReturnValues="ALL_NEW"
            )
            # There is an additional wrinkle after allocating points.
            # I wanted users to not be able to go negative.
            # Since everyone starts at 0 points I thought it would be
            # too easy for people to end up negative and then get discouraged.
            # To prevent that I update the users points to 0 if their point total
            # is negative after the previous step.
            try:
                cleanup = table.update_item(
                    Key={
                        'name': user
                    },
                    UpdateExpression="set points = :min",
                    ConditionExpression="points < :min",
                    ExpressionAttributeValues={
                        ':min': 0
                    },
                    ReturnValues="UPDATED_NEW"
                )
                resp = cleanup
            except Exception as e:
                print(e)
                resp = response

            # Get the users new point total after allocation
            total_points = resp['Attributes']['points']
            # create the response object for Slack to display
            ret = {"text": "{} has {} for a total of {} points".format(fancy_assigner,action,total_points)}
        else:
            # This handles any of the permission errors.
            # Most of them are pretty self-explanatory
            if not assignee_found: # user not found
                ret = {"text": "No such witch/wizard: {}".format(user)}
            elif assigner_permission and (not assignee_permission): # assigner can_has = False
                ret = {"text": "{} is unable to receive or lose points at the moment".format(fancy_user)}
            elif (not assigner_permission) and assignee_permission: # assignee can_has = False
                ret = {"text": "{} is unable to give or detract points at the moment".format(fancy_assigner)}
            else: # This should only happen if both assigner and assignee can_has = False
                ret = {"text": "Neither {} nor {} may alter point totals at the moment".format(fancy_user,fancy_assigner)}
    except Exception as e:
        # Catch all exception
        ret = {"text": "Error {}.".format(e)}
    return ret

# This function displays all the members of a house
# and their point totals (so you can see who's beating you in points).
def getHousePoints(table,house):
    try:
        # Again, the use of scan here bothers me, but it's not a big deal for so little data.
        response = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("house").eq(house)
        )
        items = response['Items']
        # Get the house total
        total_points = sum([i['points'] for i in items])
        # format the members into a list to display in Slack
        member_list = {}
        for i in items:
            # this used to be done with dictionary comprehension, but the
            # use of fullname and title make it too confusing so I just broke it into a loop
            n = fullNameify(i)
            member_list[n] = i['points']
        # Sort the member list so those with the most points are at the top
        sorted_members = sorted(member_list.items(), key=lambda kv: kv[1], reverse=True)
        # Respond with the list as an attachment so it'll display correctly in Slack
        members = "\n".join(["_{}_: {}".format(k,v) for k,v in sorted_members])
        ret = {"text": "{} has {} points".format(house,total_points)}
        ret["attachments"] = [{"text": members}]
    except Exception as e:
        ret = {"text": "Something went wrong: {}".format(e)}
    return ret

# Get the points of a single user.
# Great for checking if Wilbur's cheating.
# He's not, but he's got almost as many points as all of Slytherin
def getUserPoints(table,user):
    try:
        # Get the user
        response = table.get_item(
            Key={
                'name': user
            },
        )
        item = response['Item']
        total_points = item['points']
        house = item['house'].capitalize()
        # Format their name and title if present
        fname = fullNameify(item)
        ret = {"text": "_{}_ has {} points for house {}".format(fname,total_points,house)}
    except Exception as e:
        print(e)
        # Throw an error if they type an invalid name
        ret = {"text": "No such witch/wizard: {}".format(user)}
    return ret

# Clean the name, mostly just lowercase it and remove the @ from Slack
def cleanName(name):
    return name.replace("@","").replace(",","").strip().lower()

# Helper function -- Determines if input is a string representation of an integer
def isInt(s):
    try:
        assert type(s).__name__ == "str", "incorrect input type"
        int(s)
        return True
    except (ValueError,AssertionError) as e:
        return False

# Parses the points, username and message from Slack parameters.
# I originally built the app with the expectation users would type something like:
# /points @user 100
# However, I started noticing people forgot the order and did things like:
#
# /points 1000 @user
# This caused an error as the app tried to parse a name of "1000" and cast "@user" into an int.
#
# /points @user 2000 THANK YOU SO MUCH!!!
# I noticed people were leaving messages for each other when giving points.
# Since the original only checked the first 2 parameters (user & points)
# they were able to type explanations and thanks to each other and everything still worked.
# I decided this was a really cool feature so now I specifically parse out the message.
# Why?  Maybe I'll go into that in a future blog...
#
# /points @user thanks for your help
# This caused an error before the person executing the command forgot to allocate points.
# This was simple to fix, now if you don't provide points it defaults to +1000
#
# /points @user1 2000 helping me out
# /points @user2 2000 helping me out
# /points @user3 2000 helping me out
# Sometimes someone would want to thank multiple people for the same thing and have to write
# several of the same message to get everyone
#
# This block was made so it could handle all those cases:
# Sort the words in our text property into users, points and the message
def parseMessage(words):
    # users are considered anything with a @
    # we concatenate them all into a single list
    # allowing someone to award points to multiple people at once
    users = [cleanName(word) for word in words if "@" in word]
    users = list(set(users)) # remove duplicates
    # We consider points to be the first occurrence of an integer
    # in the text array. Numbers could also appear in the message
    # eg: "thanks for helping me 100 times!!"
    # So we collect all instance of integers and take the first one.
    possible_points = [num for num in words if isInt(num)]
    # If we fail to parse points we give the user default points
    points = int(possible_points[0]) if len(possible_points) > 0 else 1000 # 1000 is default
    # All other words in the text array are considered part of the message
    msg_components = [word for word in words if (word not in users and word != points)]
    msg = " ".join(msg_components) if len(msg_components) > 0 else ""
    return users,points,msg

# The event handler
# This is the part lambda sends requests through
def handlePoints(event, context):
    # Verification block
    # This block is basically ripped right from Slack's guide for handling
    # signature comparisons.
    # This is code only a mother could love.
    body = event['body']
    timestamp = event['headers']['X-Slack-Request-Timestamp']
    slack_signature = event['headers']['X-Slack-Signature']
    basestring = f"v0:{timestamp}:{body}".encode('utf-8')
    my_signature = 'v0=' + hmac.new(SLACK_KEY, basestring, hashlib.sha256).hexdigest()
    if hmac.compare_digest(my_signature, slack_signature):
        verified = True
    else:
        verified = False

    # Only proceed if the user is verified
    if verified:
        # Instantiate the table
        table = dynamo.Table('HouseMembers')
        # parse the body parameters
        params = parse_qs(event['body'])

        # This is used more for debugging than anything else.
        # The print allows me to see what the message contained
        # when I check cloudwatch logs for this lambda function
        print(params)

        if "text" in params:
            # If the request contains a text field then the user has passed some parameters.
            # We then split the text field on space character.
            text = params['text'][0].split(" ")
            try: # generic try-catch so if something breaks it doesn't cause an ugly (and scary) 502 message
                # This block looks a bit confusing, but because Slack passes the parameters of a slash command
                # as one big string we have to do a bunch of string checks and parsing in order to get the precious data.
                if len(text) == 1:
                    # If there's only one parameter then the user is either trying to get a specific users total
                    # or see the summary of all members of a house.
                    if text[0].lower() in HOUSES:
                        # if the parameter is in our houses list then we display the house summary
                        house = cleanName(text[0]) # This method is reused so /points GRYFFINDOR and /points @gryffindor both work
                        ret = getHousePoints(table,house)
                    else:
                        # If the name isn't in houses we assume it's a user they're looking for
                        # and proceed to give the user summary.
                        # If user isn't in our database the getUserPoints function will return an error message
                        user = cleanName(text[0])
                        ret = getUserPoints(table,user)
                else:
                    # We've covered the len(text) == 0 (by checking to see if it's present)
                    # and we just covered the len(text) == 1 case above.
                    # Anything else will be 2 or more.
                    # NOTE: We don't check for len(text) == 2 because the message after points
                    # could make text any length after splitting on spaces.
                    users,points,msg = parseMessage(text)
                    print(users,points,msg)
                    # One last check before we proceed.
                    # We check to see if the assigner is an Admin.
                    # If not we don't allow them to give themselves points.
                    # The only reason admins can give themselves points
                    # is so I can test the app on myself after updates.
                    assigner = params['user_name'][0]
                    agg_ret = []
                    for user in users:
                        if user == assigner and assigner not in ADMIN:
                            # If they're not an admin and they're trying to alter their own point total we
                            # return a passive-agressive message telling them of their wrong-doing.
                            # If you're wondering about the _ and :thumbsdown: in the message those are special
                            # decorators that Slack will interpret and display as italic text and an emoji respectively.
                            ret = getUserPoints(table,user)
                            ret["attachments"] = [{"text":"_It's considered bad form to give youself points. Your point total has not changed_ :thumbsdown:"}]
                            agg_ret = False
                            break
                        else:
                            # If everything is okay up to this point we proceed to actually allocating the points.
                            agg_ret.append(allocatePoints(table,user,points,assigner,msg))
                    if agg_ret:
                        ret = {"text": "\n".join(a['text'] for a in agg_ret)}
            except Exception as e:
                # Generic error catch.
                ret = {"text": "something went wrong: {}".format(e)}
        else:
            # If there is no text field then the user just type `/points`
            # and the house point total is returned
            house_points = getHouseTotals(table)
            ret = {"text": "{}".format(formatPoints(house_points))}
    else:
        ret = {"text": "Message verification failed"}
    return respond(None,ret)
